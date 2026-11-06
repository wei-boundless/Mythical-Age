# Physical Context Line Processing Architecture Plan

创建日期：2026-07-01

状态：核心收口已实施（2026-07-01）。本文同时作为上下文线路处理与四段物理算法的架构原则、目标模型、实施记录和后续审查基准。

本次已实施范围：

```text
1. PhysicalContextInputs 成为四段物理输入契约。
2. context_pipeline 统一执行 draft classify -> ledger enrichment -> final assemble -> read-only physical diagnostics。
3. provider-visible append ledger 只 enrich current append，不再决定 physical assembly 是否执行。
4. single_agent_turn follow-up 删除私有四段拼接分支，改走统一 context pipeline。
5. runtime_memory_context 改为 low-authority CONTEXT_APPEND current hint，不再声明为 confirmed old context。
6. physical_prefix_frame_user_context_replay 改为 provider_protocol_history 语义槽。
7. context contract 不再推断缺失 physical lane/index，缺线直接报 structural diagnostic。
8. physical_context_plan 去掉 lane 推断，只读取 assembler 写入的 lane/index；缺失进入 blocked_segments。
9. 前端释放/中断 stream 前会持久化当前可见 projection snapshot，断线不再清空已显示投影。
```

## 1. 目的

本文要解决的不是某一个上下文片段插错位置，而是上下文线路处理的层级边界问题。

目标是把当前散落在 compiler、harness、context pipeline、provider-visible ledger、physical assembler、physical plan 中的历史逻辑收束为一条清晰链路：

```text
上下文消息规格
-> 线路声明
-> 线路激活
-> 四段物理输入包 draft
-> provider-visible append metadata enrichment
-> 四段物理输入包 final
-> 唯一物理插线算法
-> 只读诊断与缓存脊柱 hash
-> provider payload / provider success commit
```

设计完成后，新增一条信息线时，开发者只需要声明它的物理段、生命周期、是否可封存、身份键和语义槽，不需要在多个下游模块补排序、补 metadata 或补特殊分支。

## 2. 当前设计缺口

### 2.1 直接症状

当前主链路已经把 `physical_context_assembler.py` 收束为四段插线点，但还存在这些结构性缺口：

| 缺口 | 证据 | 风险 |
| --- | --- | --- |
| 物理组装不是所有路径都会执行 | `context_pipeline.py` 只在 `PROVIDER_VISIBLE_APPEND_STAGE_INVOCATIONS` 命中并有 scope/storage 时调用 assembler | 新 invocation 可能只经过只读 plan，spec 缺少 `physical_prefix_lane` 和 `context_physical_assembly_index` |
| 分类入口分散 | 普通 pipeline 在 `context_pipeline.py` 分类，follow-up 在 `single_agent_turn.py` 分类 provider replay | 新信息线要理解多个入口，容易漏接或重复接 |
| ledger 与物理组装层级混合 | `apply_provider_visible_append_stage_to_specs()` 同时登记 current append、还调用 assembler | storage/scope 缺失会影响物理插线，层级边界不清 |
| plan 命名和职责历史残留 | `apply_physical_context_plan_to_specs()` 实际已变为只读诊断 | 容易再次把 plan 当作排序/修复层 |
| append 候选排序与本轮发送顺序存在双重语义 | ledger 内用 `context_append_order_key()` 遍历候选，pipeline 又按 original order 还原 current append | 当前可控，但未来如果用 ledger entry index 还原消息顺序会破坏用户消息/记忆/工具 transcript 的自然上下文顺序 |

### 2.2 深层原因

历史代码把三类不同问题混在了同一层：

```text
物理段分类：这条线属于 static / old / current / dynamic 哪一段
生命周期处理：这条线是否可被 provider success 封存
物理插线：四段按什么顺序进入模型消息
```

正确结构应该是先在插线前完成分类与生命周期判断，然后由唯一物理算法拼接。插线后只能做诊断、hash 和记录，不能再排序、补线或重新解释语义。

## 3. 架构原则

### 3.1 线路先声明，后插线

每条上下文线必须先拥有明确声明：

```text
kind
source
producer_ref
transport_or_store
consumer
physical_segment
semantic_slot
identity_key
lifecycle
sealability
provider_visibility
context_line_state
activation_authority
disabled_reason
terminal_policy
schema_revision
```

未声明的线不能靠下游 fallback 猜测物理段。下游如果看不懂线路，应产生结构诊断，而不是把它塞进某个默认段。

### 3.2 系统资产必须有线，activation 决定本轮是否通线

每个系统资产都必须有对应线路声明。资产可以不在某一轮进入上下文，但不能因为未启用就没有线路定义。

```text
系统资产存在
-> 必须声明 SystemAssetLine
-> 每轮由 context_line_state 决定是否进入 PhysicalContextInputs
```

推荐状态：

```text
enabled
disabled
unavailable
blocked
diagnostic_only
```

规则：

```text
enabled 才能进入四段输入包
disabled/unavailable/blocked 只进入诊断，不进入 message_specs
diagnostic_only 可进入 plan/report，不进入 provider-visible payload
disabled_reason 必须可追踪
activation_authority 必须明确
```

这个开关只能在插线前生效。禁止先插线，再在 plan、present 或 provider payload 层过滤掉 disabled 资产。

### 3.3 分类只发生在插线前

允许在插线前做这些事情：

```text
normalize message spec
读取 context_line_state
读取 context_segment_policy
判定 static / old / current / dynamic
登记 provider-visible current append candidate
识别 provider protocol replay / physical frame replay
识别 dynamic tail / never replay tail
```

禁止在插线后做这些事情：

```text
重新排序
重新分段
把 current append 提前当 old context
把 dynamic tail 写入 confirmed old context
按 semantic slot 修复物理顺序
由 harness 手工拼 static + old + current + tail
```

### 3.4 物理插线只能有一个 authority

唯一物理插线 authority 是：

```text
runtime.context_management.physical_context_assembler
```

它只接收已经分类好的四段输入包，输出最终 message specs，并写入：

```text
physical_prefix_lane
context_physical_assembly_index
```

compiler、harness、ledger、plan、diagnostics 都不能再拥有最终消息顺序决策权。

### 3.5 provider-visible ledger 不是物理排序权威

provider-visible append ledger 的职责是：

```text
登记 current append candidate
根据 provider success 确认 candidate
维护 item_key / provider_visible_hash / entry_index
为 physical prefix frame commit 提供确认依据
```

它不负责：

```text
回放完整旧上下文
决定四段物理顺序
用 entry_index 重排 provider payload
替代 physical prefix frame
```

### 3.6 physical plan 只读

`build_physical_context_plan()` 只能读取已经组装好的顺序，用于：

```text
lane order diagnostics
cache spine hash
stable-after-tail violation
segment visibility / validity scope diagnostics
```

它不能改变 specs，也不能为上游遗漏的 `physical_prefix_lane` 或 index 兜底补线。

### 3.7 current 优先于旧状态

当前用户输入、当前 steer、当前工具观察、当前 active lease 和恢复反馈不能被旧记忆、旧计划、旧摘要覆盖。旧上下文只提供历史事实，不拥有当前轮裁决权。

### 3.8 语义空间服务物理段，不反向覆盖物理段

语义 slot 用来帮助 agent 理解内容类型，例如：

```text
current_user_intent
selected_memory_and_task_state_facts
provider_protocol_history
tool_transcript
evidence_refs_and_file_state_facts
active_execution_lease
```

但 semantic slot 不能越权决定 provider cache boundary，也不能在插线后重排四段。

### 3.9 上下文输入端与控制输出端分离

上下文是系统收集信息后提供给 agent 读取的输入端；控制输出端是 agent 决策后反向输出控制信息给系统的输出端。两端通过模型决策连接，但不能互相越权。

```text
system observation / user input / memory hint / tool observation / frontend projection signal
-> context center packet
-> agent model decision
-> control output packet
-> system actuator / tool / task / frontend / memory side effect
-> observation line
-> next context center packet
```

规则：

```text
上下文中枢不能执行动作
控制输出端不能补写、重排、推断上下文
外周器官只能产出 observation / projection / durable candidate，不能直接成为上下文权威
恢复信号不是旧上下文；只能作为 recovery_or_recent_work_facts 进入 dynamic/current recovery line
```

## 4. 总线路处理模型

目标模型分为七层。

### 4.1 Line Declaration

输入：

```text
message spec
kind
metadata
model_message
source_ref
```

输出：

```text
ContextLineDeclaration
```

职责：

```text
声明 kind 属于哪一类上下文线
声明系统资产对应的线路
声明默认 physical_segment
声明 semantic_slot
声明 lifecycle 和 sealability
声明 identity_key 来源
声明 activation 字段及其默认状态
```

候选落点：

```text
backend/runtime/context_management/context_segment_registry.py
backend/runtime/context_management/context_segment_policy.py
```

### 4.2 Line Activation

输入：

```text
ContextLineDeclaration
system asset availability
invocation facts
runtime capability/profile state
```

输出：

```text
ActivatedContextLine
```

职责：

```text
判断本轮是否启用该系统资产线
写入 context_line_state
写入 activation_authority
写入 disabled_reason / blocked_reason
不决定四段顺序
不生成最终 message_specs
```

目标字段：

```json
{
  "context_line_state": "enabled",
  "context_line_activation_authority": "runtime.context_management.line_activation",
  "context_line_disabled_reason": ""
}
```

只有 `context_line_state == enabled` 的线路可以进入 `PhysicalContextInputs`。

### 4.3 Line Classification

输入：

```text
ContextLineDeclaration
ActivatedContextLine
message spec metadata
provider replay contract
current invocation facts
```

输出：

```text
PhysicalContextInputs(draft)
```

固定结构：

```python
PhysicalContextInputs(
    static_prefix_specs=...,
    old_context_replay_specs=...,
    current_append_specs=...,
    dynamic_tail_specs=...,
)
```

职责：

```text
只分段，不拼接
只把线放进四个物理篮子
只消费 enabled 线路
不写最终 physical index
不读取 provider success ledger 作为最终 replay 顺序
输出 draft；current_append 允许随后被 ledger enrich，但段归属不能被 ledger 改写
```

### 4.4 Provider Visible Append Registration

输入：

```text
PhysicalContextInputs(draft).current_append_specs
provider/model/scope
storage_root
```

输出：

```text
current append specs enriched with provider_visible_append_* metadata
provider-visible append ledger records
PhysicalContextInputs(final)
```

职责：

```text
登记当前可封存候选
保持本轮 current append 的输入顺序
去重和 hash 校验
不回放旧上下文
不触发或跳过物理组装
scope/storage 缺失时只返回 ledger skipped diagnostics，PhysicalContextInputs(final) 必须保留 draft 的四段内容
```

### 4.5 Physical Assembly

输入：

```text
PhysicalContextInputs(final)
latest confirmed physical prefix frame
```

输出：

```text
final message_specs
physical lane metadata
physical assembly index
assembly diagnostics
```

唯一顺序：

```text
static_prefix
-> confirmed_old_context
-> current_append
-> dynamic_tail
```

### 4.6 Read-Only Physical Plan

输入：

```text
final message_specs
```

输出：

```text
physical plan diagnostics
cache_spine_hash
lane_order
stable_after_tail_violations
```

职责：

```text
只读
不排序
不补 metadata
不改变消息
```

### 4.7 Provider Commit

输入：

```text
provider request payload
provider success result
provider-visible append confirmations
physical payload manifest
```

输出：

```text
confirmed provider-visible entries
physical prefix frame
provider cache diagnostics
```

职责：

```text
只有 provider success 后 current append 才能晋升为下一轮 old context
失败、取消、中断不能把 current append 写成 confirmed old context
dynamic tail 永远不进入 confirmed old context
```

### 4.8 上下文中枢与控制输出端架构审查

本节补充对用户提出的“上下文是不是 agent 中枢、控制器是不是另一端”的架构审查。结论是：这个模型可以成立，但不能表述为“收束到一个核心控制器”。更准确的目标是：

```text
收束到一个上下文中枢 + 一个控制输出端
```

上下文中枢保存 agent 本轮可感知的信息态；控制输出端承接模型决策，把决策变成可授权、可执行、可观察的动作。tools、tasks、files、memory、frontend projection 都是外周器官或事实源，不是第二个中枢。

目标单向流：

```text
SystemAssetLine / 用户输入 / provider protocol / memory hint / tool observation / frontend replay signal
-> Line Declaration
-> Line Activation
-> PhysicalContextInputs
-> Context Center Packet
-> provider model decision
-> ModelActionRequest
-> Admission / ActionPermit
-> organ actuator
-> observation / commit / projection
-> ObservationLine
-> 下一轮 Context Center Packet
```

其中：

```text
上下文中枢 = 四段物理上下文 + context contract diagnostics + cache spine identity
控制输出端 = action_surface + provider control action transport + ModelActionRequest + admission/permit + execution feedback
外周器官 = tool runtime / task resource / file evidence / memory system / public stream frontend
```

#### 4.8.1 已经接准的线

| 线 | 当前代码证据 | 审查结论 |
| --- | --- | --- |
| 请求进入 turn 中枢前先形成运行事实 | `runtime_facade.astream()` 先汇总 `runtime_assembly`、`turn_input_facts`、`current_work_boundary_receipt`、`memory_context`，再进入 `run_single_agent_turn()` | 请求事实和当前工作边界已经在 harness 入口侧收口 |
| 控制输出端已有单向链 | `RuntimePacketContext.allowed_action_types` -> `build_tool_call_contract()` -> `provider_control_action_bindings()` -> `ModelActionRequest` -> `admit_model_action()` -> `ActionPermit` -> `RuntimeToolControlPlane.invoke()` | 控制端雏形是成熟的，后续重点是防止它反向决定上下文 |
| 四段物理算法已有唯一插线函数 | `assemble_physical_context_spine()` 输出 `physical_prefix_lane` 和 `context_physical_assembly_index`，顺序为 static -> old -> current -> dynamic | 方向正确，应升级为所有 invocation 必经的中枢插线点 |
| provider-visible ledger 已被限制为候选登记 | `assemble_provider_visible_append_specs()` 注释明确“不回放 confirmed provider messages”，只返回 current append candidates | ledger 不是替代品，不能替代四段拼接或旧上下文回放 |
| context segment registry 已有线路声明雏形 | `context_segment_registry.py` 已集中声明 kind / section / semantic_slot / capability / layer | 应升级为 `ContextLineDeclaration` / `SystemAssetLine`，而不是再建平行语义表 |

#### 4.8.2 尚未接准的线

| 严重度 | 断线 | 代码证据 | 风险 | 修复方向 |
| --- | --- | --- | --- | --- |
| P1 | provider append stage skipped 时，physical assembly 也被跳过 | `context_pipeline.py` 在缺少 scope/storage 或 invocation kind 不命中时直接返回 clean specs，随后只运行 read-only plan | message specs 可能没有真实 `physical_prefix_lane` / `context_physical_assembly_index`；上下文中枢没有形成 | 分离 ledger skipped 与 assembly skipped；所有 invocation 都必须进入 assembler |
| P1 | follow-up 仍由 harness 私有分类四段输入 | `single_agent_turn.py` 的 `_single_agent_turn_followup_physical_context_assembly()` 自己分类 static / old replay / append / dynamic | 控制输出端附近再次拥有上下文分类权，容易和 pipeline 主算法漂移 | follow-up 只做 provider protocol replay 标记，然后交给统一 `classify_physical_context_inputs()` |
| P1 | context contract 诊断会在缺少 lane 时推断 lane | `context_contract.authority_rules._physical_lane()` 缺少 metadata 时调用 `physical_lane_for_spec()`；`manifest._physical_lane_edge()` authority 仍指向 `physical_context_plan` | 诊断层可能掩盖 assembler 未执行的问题，把缺线误报成已接线 | context contract 只能读取 assembler 写入的 lane/index；缺失时报告 structural gap，不能 fallback 推断 |
| P1 | `runtime_memory_context` 在 assembler skipped 时可能被诊断成 old prefix | `runtime_memory_context` 默认声明为 `CONTEXT_MEMORY_PREFIX`，正常 pipeline 会作为 current append 交给 assembler；但 `physical_lane_for_spec()` 会把 `CONTEXT_MEMORY_PREFIX` 映射成 `provider_visible_context_prefix` | memory hint 被误看成 confirmed old context，造成“摘要替代旧上下文”的错觉 | `PhysicalContextInputs` 必须显式区分 confirmed_old_context 与 current memory hint |
| P2 | capability filter 还不是 SystemAssetLine activation | `apply_context_capability_profile()` 直接 keep/reject specs，只产出 rejected diagnostics | disabled asset 没有稳定线路身份，后续难追踪“资产存在但本轮未通线” | 改为先声明 `SystemAssetLine`，再由 `context_line_state` 决定是否进入四段输入 |
| P2 | ledger 内部仍按 semantic slot rank 遍历候选 | `provider_visible_append_ledger.py` 对 candidates 使用 `context_append_order_key()`；pipeline 再按 original order 还原 current append | 当前发送顺序可控，但未来若误用 ledger entry index 或 rank 作为 provider payload 顺序，会破坏自然上下文顺序 | ledger 可用 rank 做去重/登记辅助，但 physical payload 顺序只看 `PhysicalContextInputs` 输入顺序 |
| P2 | task execution 仍残留第二套 action request | `TaskExecutionModelActionRequest` 仍存在；历史标准化计划也标记普通 task executor 是第二套模型循环 | 这是控制输出端的历史冗余，不直接阻断本计划，但会影响后续神经系统收束 | 另按 Turn runtime 计划资源化 TaskRun；本计划只禁止它参与上下文物理拼接 |

#### 4.8.3 权威边界表

| 层 | 唯一权威 | 允许 | 禁止 |
| --- | --- | --- | --- |
| 线路声明 | `runtime.context_management.context_segment_registry`，目标升级为 `ContextLineDeclaration` | 声明 kind、物理段、语义槽、生命周期、系统资产线 | 根据本轮状态决定是否启用 |
| 线路激活 | 目标 `runtime.context_management.context_line_activation` | 读取 profile、asset availability、invocation facts，写入 `context_line_state` | 生成最终 message order |
| 四段分类 | 目标 `classify_physical_context_inputs()` | 把 enabled lines 放入 static / old / current / dynamic | 写 final index；回放 ledger old context |
| 物理插线 | `runtime.context_management.physical_context_assembler` | 生成最终 message specs，写 lane/index | 根据 semantic slot 二次排序；跳过 disabled asset 后再补线 |
| 只读诊断 | `physical_context_plan` 与 `harness.runtime.context_contract` | 读取已组装顺序，生成 hash、edge、问题报告 | 推断缺失 lane/index；改变 message specs |
| 控制输出端 | `harness.runtime.packet_context`、`harness.loop.model_action_request`、`harness.loop.admission`、`harness.loop.action_permit` | 定义动作面、承接模型决策、授权或拒绝动作、返回反馈 | 发明上下文、重排上下文、把 tool failure 改写成用户目标 |
| 外周器官 | tool runtime / task system / memory system / frontend public stream | 执行动作、产出 observation、展示 projection、提供候选事实 | 直接写入上下文中枢；绕过 line activation |

#### 4.8.4 每类外周器官的回流线

| 器官 | 输出 | 回流到上下文中枢的线 | 权威 |
| --- | --- | --- | --- |
| Tool runtime | tool observation / permission denial / execution error | `tool_transcript` 或 `ActionFeedback` -> current/dynamic | tool observation 是事实；是否继续由模型下一步决定 |
| Task resource | active lease / todo cursor / task state projection | `active_execution_lease` / `task_*_context` -> dynamic tail | 当前控制态，不是 confirmed old context |
| File evidence | read refs / file state summary / exact snippets | `read_evidence_context` / `read_evidence_injection` -> current/dynamic | 文件证据高于 memory hint |
| Memory system | selected memory / conversation continuity / durable candidates | `runtime_memory_context` -> current append hint | memory 是低权威提示，不替代 provider protocol history |
| Frontend projection | public stream cursor / visible projection cache / reconnect replay | public projection only，必要时作为 recovery signal 入 dynamic tail | 前端只能展示和恢复可见投影，不能成为上下文权威 |

#### 4.8.5 对计划的直接修正

本计划后续实施必须额外满足：

```text
1. `PhysicalContextInputs` 是上下文中枢的唯一四段输入包。
2. `ContextLineDeclaration` 必须覆盖所有 system asset；未启用资产也要有 diagnostics。
3. `context_line_state != enabled` 的线路不能进入 message_specs。
4. `runtime_memory_context`、conversation continuity、session emphasis 都是 memory hint/current append，不是 confirmed old context。
5. context contract 只能读 assembler lane/index；缺失 lane/index 必须报错，不能推断。
6. control/action/admission/tool/runtime projection 都不能重排或补写上下文线。
7. frontend 断线恢复只恢复 public projection 和 stream cursor；如需让 agent 感知恢复事实，必须作为 dynamic recovery line 进入下一轮上下文中枢。
8. `PhysicalContextInputs` 必须区分 draft/final：ledger 可以 enrich current append metadata，但不能改变四段归属。
9. `runtime_memory_context` 必须从 `CONTEXT_MEMORY_PREFIX` 语义中剥离为低权威 current hint，不能靠 classifier 事后纠偏。
10. old replay 里的历史用户消息不能继续使用 `current_user_intent` 语义槽，应转为 historical/provider protocol history 语义。
11. provider success commit 必须显式处理 success / failure / cancel / interrupt，只有 success 能晋升 frame。
12. frontend replay 必须按 stable event identity 和 projection key 幂等合并，断线不能清空已显示 projection。
13. cutover 只能是 clean cutover；不得新增长期双跑或兼容旧主链路。
```

#### 4.8.6 断线时间与替代品判断

从 `git blame` 看，断线不是单点事故，而是两次结构移动叠加出来的：

| 时间 | commit | 变化 | 架构影响 |
| --- | --- | --- | --- |
| 2026-06-27 01:42:24 +0800 | `3d7f5677d` | 新增 `context_pipeline.py`，`apply_provider_visible_append_stage_to_specs()` 在缺少 scope/storage 或 invocation kind 不命中时直接 skipped | 当时是 append stage 的边界条件；后续如果把物理拼接放进这个 stage，就会继承 skipped 语义 |
| 2026-06-29 06:06:59 +0800 | `0f157952d` | 新增 `physical_context_assembler.py`，并在 `context_pipeline.py` 的 append stage 内调用 `assemble_physical_context_spine()`；同批次在 `single_agent_turn.py` 新增 `_single_agent_turn_followup_physical_context_assembly()` | 四段 assembler 已经出现，但接在线路登记 stage 后面，不是所有 invocation 必经；follow-up 同时形成第二条私有分类/拼接线 |
| 2026-07-01 01:21:06 +0800 | `9ef082f83` | 调整 provider-visible append scope、provider lane、follow-up 字段命名 | 属于后续优化，没有改变“assembly 依附 append stage”和“follow-up 私有分类”这两个结构问题 |

结论：

```text
不是出现了成熟替代品。
provider_visible_append_ledger 只能登记 current append candidate，不能替代四段拼接。
physical_context_plan 只能做只读诊断/hash，不能替代 assembler。
_single_agent_turn_followup_physical_context_assembly 是历史私有分支，不是第二套主算法。
```

因此实施时不能保留这些分支作为兼容主路径。正确收口是：

```text
append ledger skipped != physical assembly skipped
follow-up provider protocol replay marking != follow-up private physical assembly
diagnostic lane projection != fallback lane inference
```

#### 4.8.7 审查补充后的强制设计约束

| 缺口 | 证据 | 必须补入实施设计 |
| --- | --- | --- |
| `PhysicalContextInputs` 与 ledger 顺序不够锁定 | 计划前文曾写 `provider-visible append 登记 -> 四段物理输入包`，但 4.3/4.4 的职责实际应是 draft inputs -> ledger enrich -> final inputs | 明确 draft/final 两步；ledger skipped 只影响 metadata/diagnostics，不影响 assembly |
| `runtime_memory_context` 与 current hint 原则冲突 | 现有 `context_segment_registry.py` / `context_segment_policy.py` 仍把 `runtime_memory_context` 放入 `CONTEXT_MEMORY_PREFIX` | Phase 1/2 必须把 memory 声明为 low-authority current hint；不能让 memory summary 冒充 confirmed old context |
| old replay 使用 current 语义槽 | `physical_prefix_frame_user_context_replay` 当前仍可落到 `current_user_intent` | 历史用户消息应归入 `provider_protocol_history` 或 `historical_user_message`，不再使用本轮 current 语义 |
| commit terminal cases 未阶段化 | 4.7 有原则，但 Phase 1-7 没有专门闭合 success/failure/cancel/interrupt | 增加 provider commit boundary 阶段；只允许 provider success 晋升 frame，失败/取消/中断只能留下 diagnostics/recovery line |
| frontend projection 缺少幂等合同 | 前端已有 cursor/projection reducer，但计划只写了不伪造上下文 | 明确 `runtime_event_id` / cursor / projection key / source event identity 是 replay merge key；reconnect 不得清空已显示 projection |
| cutover 规则不够工程化 | 禁止兼容旧主链路已有，但缺少执行边界 | 新链路落地即删除旧 active branch；失败回滚依赖 git/service rollback，不在代码里保留 v1/v2 双跑 |
| `SystemAssetLine` 字段不足以追踪端到端 | 只有 kind/source/segment 等字段，缺 producer/transport/consumer/terminal/schema | Line Declaration 必须包含 producer_ref、transport_or_store、consumer、terminal_policy、schema_revision |

## 5. 四段物理算法

### 5.1 固定算法

目标代码形态：

```python
def assemble_physical_context_spine(inputs: PhysicalContextInputs, frame_ref: PhysicalFrameRef | None) -> PhysicalContextAssemblyResult:
    static = with_lane(inputs.static_prefix_specs, GLOBAL_STATIC_PREFIX)
    old = with_lane(resolve_old_context(inputs.old_context_replay_specs, frame_ref), PROVIDER_VISIBLE_CONTEXT_PREFIX)
    current = with_lane(inputs.current_append_specs, CURRENT_TURN_TAIL)
    dynamic, never = split_dynamic_tail(inputs.dynamic_tail_specs)
    return index([*static, *old, *current, *dynamic, *never])
```

算法稳定性要求：

```text
static 段保持输入顺序
old 段优先使用显式 old_context_replay_specs；否则从 latest confirmed physical prefix frame 按 ordinal 回放
current 段保持当前请求输入顺序
dynamic 段保持当前请求输入顺序
never_replay_tail 位于最后
插线后不允许任何二次排序
```

### 5.2 static_prefix

物理 lane：

```text
global_static_prefix
```

语义：

```text
稳定协议、agent 身份、环境边界、项目规则、工具目录、action schema、任务运行契约
```

来源例子：

```text
global_static
agent_stable
personality_stable
environment_stable
project_instructions_stable
action_schema_static
capability_catalog
tool_index_stable
task_prompt_contract
task_environment_context
```

规则：

```text
必须稳定
可参与 cache spine
不能包含当前用户请求
不能包含当前工具观察
不能包含恢复反馈
```

### 5.3 confirmed_old_context

物理 lane：

```text
provider_visible_context_prefix
```

语义：

```text
已经 provider success 确认过的历史正文、工具轮、用户/assistant provider protocol message、已封存的上下文事实
```

来源：

```text
physical prefix frame replay
provider protocol replay during follow-up
confirmed provider-visible append entries promoted into frame
```

规则：

```text
按 physical frame ordinal 回放
provider protocol replay 只作为当前 follow-up 已发送前缀的 byte-preserve old input
不按 semantic slot 重排
不按 ledger entry index 全量重排
未闭合工具轮不能进入 confirmed old context
```

### 5.4 current_append

物理 lane：

```text
current_turn_tail
```

语义：

```text
本轮新增、当前可见、尚未 provider success 确认的上下文
```

来源例子：

```text
current_turn_user_context
single_agent_turn_user_steer_context
runtime_memory_context
provider_protocol_history append candidate
tool_transcript_delta
read_evidence_context
evidence_index_cursor
task_state_replay_entry
session_pinned_facts_context
```

规则：

```text
保持当前请求输入顺序
可以登记为 provider-visible append candidate
只有 provider success 后才能进入下一轮 confirmed old context
current user 不得被旧历史替代
runtime memory 是低权威事实提示，不能替代 provider protocol history、当前用户输入或 read evidence
```

### 5.5 dynamic_tail / never_replay_tail

物理 lane：

```text
current_turn_tail
never_replay_tail
```

语义：

```text
当前轮控制、任务游标、active lease、恢复反馈、缺失证据 horizon、动态边界、一次性操作契约
```

来源例子：

```text
task_goal_context
task_plan_context
task_todo_context
active_execution_lease
turn_operating_contract
runtime_control_signal_tail
partial_stream_recovery_instruction
recovery_context_package
evidence_acquisition_horizon
active_skills
```

规则：

```text
永远位于物理末尾
默认不参与 cache spine
不能晋升为 confirmed old context
不能污染 provider-visible ledger
用于当前行动边界，而不是历史事实
```

## 6. 每段语义空间架构

### 6.1 语义空间不是第五段

语义空间是每段内部的解释结构，不是额外物理段。它回答：

```text
这条线是什么事实？
它的时间属性是什么？
它的权威等级是什么？
agent 应该怎样消费它？
它是否能进入下一轮历史？
```

### 6.2 建议语义槽

| 语义槽 | 物理段 | 权威等级 | 用途 |
| --- | --- | --- | --- |
| `static_protocol` | static | 高 | 系统/工具/环境固定契约 |
| `provider_protocol_history` | old/current | 高 | 真实 user/assistant/tool provider-visible 时间线 |
| `current_user_intent` | current | 最高当前权威 | 本轮用户输入 |
| `active_user_steer_content` | current | 高 | 本轮用户修正/转向 |
| `selected_memory_and_task_state_facts` | current | 中低 | 记忆和任务状态提示，不替代正文事实 |
| `tool_transcript` | old/current | 高 | 闭合工具轮和当前工具观察 |
| `evidence_refs_and_file_state_facts` | current | 高 | 文件证据 refs/hash/range/freshness |
| `active_execution_lease` | dynamic | 当前控制权威 | 当前是否应继续执行 |
| `recovery_or_recent_work_facts` | dynamic | 当前恢复权威 | 恢复/中断后提示 |
| `runtime_control_contract` | dynamic | 控制 | 本轮操作边界 |

### 6.3 合理语义空间的判定

一轮最终上下文应满足：

```text
static 说明 agent 是谁、能做什么、边界是什么
old 说明过去真实发生了什么
current 说明本轮用户要什么、目前看到哪些事实和工具观察
dynamic 说明当前要怎样行动、哪些状态只在本轮有效
```

不合理形态：

```text
old 缺失真实 provider protocol history，只剩 memory summary
current user 被 seal 成长期历史替代品
dynamic tail 出现在 stable prefix 之前
runtime memory 在 current user 之前覆盖用户意图
工具轮未闭合却进入 old context
plan/todo 旧游标压过当前 active lease
```

## 7. 具体优化方案

### Phase 1: 固化线路声明

目标：

```text
让每种 kind 和每个系统资产都有明确 physical_segment / semantic_slot / lifecycle / sealability / activation / identity / terminal policy
```

文件：

```text
backend/runtime/context_management/context_segment_registry.py
backend/runtime/context_management/context_segment_policy.py
backend/runtime/context_management/provider_message_replay_contract.py
```

动作：

```text
补齐 ContextLineDeclaration 概念
补齐 SystemAssetLine / context_line_state 概念
补齐 producer_ref / transport_or_store / consumer / terminal_policy / schema_revision
把 replay contract、append candidate、dynamic only 明确分型
把 runtime_memory_context 声明为 low-authority current hint，不再声明为 confirmed old context
把 historical user replay 从 current_user_intent 语义槽中剥离
删除靠 content_source/source_kind 字符串猜测物理段的残余
```

完成条件：

```text
新增信息线只需在 registry/policy 声明，不需要修改 downstream 排序逻辑
系统资产未启用时有 disabled_reason，不会进入 message_specs
runtime_memory_context 不再通过 CONTEXT_MEMORY_PREFIX 冒充 confirmed old context
physical prefix frame 的历史用户 replay 不再使用 current_user_intent 作为语义槽
rg 检查不再出现旧 replay 或 old-context 字段作为 active 决策分支
```

### Phase 2: 抽出 PhysicalContextInputs

目标：

```text
让四段输入成为显式数据结构，而不是多个局部 list
```

文件：

```text
backend/runtime/context_management/physical_context_assembler.py
backend/runtime/context_management/context_pipeline.py
backend/harness/loop/single_agent_turn.py
```

动作：

```text
新增 PhysicalContextInputs
新增 classify_physical_context_inputs()
PhysicalContextInputs 分为 draft/final 两个语义阶段；数据结构可以相同，但 diagnostics 必须标明阶段
classify_physical_context_inputs() 只消费 context_line_state == enabled 的线路
assembler 只接收 PhysicalContextInputs
harness 不再维护任何 follow-up 私有四段分类
```

完成条件：

```text
assemble_physical_context_spine() 调用点只传 PhysicalContextInputs
ledger enrich 后输出 final PhysicalContextInputs，四段归属与 draft 一致
single_agent_turn.py 不出现 static_prefix/provider_visible_append_specs/dynamic_tail 四段局部拼装变量
```

### Phase 3: 分离 ledger 与 physical assembly

目标：

```text
provider-visible append ledger 只登记 current append，不控制是否进入 physical assembly
```

文件：

```text
backend/runtime/context_management/context_pipeline.py
backend/runtime/context_management/provider_visible_append_ledger.py
```

动作：

```text
把 apply_provider_visible_append_stage_to_specs 拆成 ledger enrichment
不再由 storage/scope 缺失决定是否执行 assembler
scope/storage 缺失只让 ledger skipped，四段插线仍执行
ledger skipped 时 current_append_specs 原样进入 final PhysicalContextInputs，并附带 skipped diagnostics
```

完成条件：

```text
所有 invocation 都经过 physical assembler
provider-visible append stage skipped 时 message_specs 仍有 physical_prefix_lane 和 context_physical_assembly_index
provider_visible_append_ledger 不产生 old replay，不输出 physical order
```

### Phase 4: 删除 follow-up 私有物理链路

目标：

```text
initial、single turn、tool follow-up、observation follow-up 共用同一分类和插线算法
```

文件：

```text
backend/harness/loop/single_agent_turn.py
backend/runtime/context_management/followup_context_rebase.py
```

动作：

```text
followup_context_rebase 只做 provider protocol replay / current append 标记
删除 follow-up 私有 physical assembly 函数
follow-up 调用 context management 统一链路
```

完成条件：

```text
rg _single_agent_turn_followup_physical_context_assembly 无 active 定义
follow-up 不再手工拼接任何四段数组
```

### Phase 5: 收口 physical plan 命名和职责

目标：

```text
plan 名称和行为都明确为只读诊断
```

文件：

```text
backend/runtime/context_management/physical_context_plan.py
backend/runtime/context_management/context_pipeline.py
backend/runtime/context_management/README.md
backend/harness/runtime/compiler.py
```

动作：

```text
把 apply_physical_context_plan_to_specs 改名为 build/read physical diagnostics
删除所有暗示 plan 会 apply/reorder/annotate 的命名
manifest 读取 assembler 已写入的 lane/index
```

完成条件：

```text
active code 中 plan 不修改 specs
rg annotate_specs_with_physical_context_plan 无 active 结果
```

### Phase 6: 语义空间审计

目标：

```text
确认四段内部语义内容完整、顺序合理、权威不串线
```

文件：

```text
backend/runtime/context_management/context_segment_registry.py
backend/harness/runtime/compiler.py
backend/harness/runtime/context_message_producers.py
backend/runtime/context_management/context_prefix_identity.py
```

动作：

```text
检查 current_user_intent 是否总在 current append 且不被 old/memory 覆盖
检查 provider_protocol_history 是否能保留普通 user/assistant 正文
检查 runtime_memory_context 是否保持 low-authority hints
检查 active_execution_lease / recovery / action horizon 是否保持 dynamic tail
```

完成条件：

```text
四段语义矩阵完整
无 stable-after-tail violation
无 dynamic tail 晋升 old context
```

### Phase 7: 收口上下文合同与控制输出边界

目标：

```text
让 context contract、prompt manifest、public projection 都只读取上下文中枢结果，不替代上下文中枢；让控制输出端只消费上下文，不反向补线。
```

文件：

```text
backend/harness/runtime/context_contract/authority_rules.py
backend/harness/runtime/context_contract/manifest.py
backend/harness/runtime/context_contract/diagnostics.py
backend/harness/runtime/packet_context.py
backend/harness/runtime/tool_call_contract.py
backend/harness/loop/admission.py
backend/runtime/output_stream/public_stream_compiler.py
frontend/src/lib/store/runtime.ts
frontend/src/lib/api/chatStream.ts
```

动作：

```text
context contract 不再用 physical_lane_for_spec 推断缺失 lane
physical_lane_projection edge authority 从 physical_context_plan 改为 physical_context_assembler
缺少 physical_prefix_lane / context_physical_assembly_index 时报告 structural gap
packet/action/admission 只记录 action_surface、ModelActionRequest、permit，不读取或重排 context specs
public stream/frontend projection 只恢复可见投影和 cursor；如需让 agent 感知，作为 dynamic recovery line 回流
frontend replay 以 runtime_event_id / source_event_id / projection key / cursor offset 幂等合并
store reducer 只能保留、合并、终止 public projection，不能生成 provider/model context
```

完成条件：

```text
context_contract diagnostics 能暴露 assembler skipped，而不是用 policy fallback 掩盖
control output 代码中没有新的上下文分类或四段拼接逻辑
frontend projection cache 不作为 provider/model context 来源
断线重连不会清空已有 projection；重复 replay 不创建重复可见事件
```

### Phase 8: 收口 provider commit 与 terminal boundary

目标：

```text
把 current append 晋升 confirmed old context 的条件收束到 provider success commit；失败、取消、中断只能留下诊断或恢复线。
```

文件：

```text
backend/runtime/context_management/provider_visible_append_ledger.py
backend/runtime/context_management/physical_prefix_frame_ledger.py
backend/runtime/context_management/context_commit_record.py
backend/runtime/model_gateway/model_runtime.py
backend/runtime/model_gateway/provider_payload.py
```

动作：

```text
明确 success / failure / cancel / interrupt 的 terminal policy
只有 provider success 且 provider payload manifest 与 physical assembly identity 匹配时，append candidate 才能 confirm
只有 confirmed append entries 能进入 physical prefix frame
failure / cancel / interrupt 不写 confirmed frame，只写 diagnostics / recovery_or_recent_work_facts
dynamic tail、frontend projection、ActionFeedback 永不晋升 confirmed old context
```

完成条件：

```text
provider success 是唯一 frame promotion 入口
失败、取消、中断不会产生 confirmed provider-visible entries
下一轮 old context 只来自 latest confirmed physical prefix frame 或 explicit provider protocol replay
```

## 8. 文件级执行清单

| 文件 | 当前角色 | 目标行动 | 完成条件 |
| --- | --- | --- | --- |
| `context_segment_registry.py` | kind/section 注册 | 升级为线路声明入口 | 每个 context kind 都有明确物理段和语义槽 |
| `context_segment_policy.py` | section/cache/seal policy | 保持预分类 authority，并承载 activation 默认状态 | 不再被下游 override |
| `context_line_activation.py` | 尚未独立存在 | 新增或等价收口 activation owner | 系统资产是否进入本轮上下文只由该层决定 |
| `provider_message_replay_contract.py` | byte-preserve/replay 判断 | 分清 append candidate、provider protocol replay、physical frame replay | byte preserve 不等于已封存 |
| `provider_visible_append_ledger.py` | current append ledger | 只登记/确认候选 | 不回放旧上下文、不控制物理排序 |
| `physical_prefix_frame_ledger.py` | confirmed old context frame | 只在 provider success 后晋升 confirmed frame | failure/cancel/interrupt 不产生 confirmed frame |
| `context_commit_record.py` | provider/session context commit record | 记录 commit terminal identity | success/failure/cancel/interrupt 可追踪且不串线 |
| `physical_context_assembler.py` | 物理插线 | 接收 `PhysicalContextInputs`，唯一写 lane/index | 所有路径都通过它 |
| `physical_context_plan.py` | physical diagnostics | 只读诊断/hash | 不排序、不 annotate specs |
| `context_pipeline.py` | 上下文流水线 | 拆出分类、ledger、assembly、diagnostics | storage/scope 缺失不跳过 assembly |
| `single_agent_turn.py` | tool loop/follow-up | 删除私有物理分类和拼接 | follow-up 共用统一 pipeline |
| `followup_context_rebase.py` | follow-up rebase | 只做插线前标记 | 不拥有四段顺序 |
| `compiler.py` | runtime packet assembly | 消费统一输出 | 不直接重组物理段 |
| `harness/runtime/context_contract/authority_rules.py` | context node 分类与诊断 | 只读取 assembler 写入的 lane/index | 缺失 lane/index 报 structural gap，不调用 policy fallback 当作真实 lane |
| `harness/runtime/context_contract/manifest.py` | context edge manifest | physical lane edge authority 指向 assembler | 不再把 physical plan 当 lane authority |
| `harness/runtime/packet_context.py` | action surface 数据源 | 保持控制输出端入口 | 不产生或重排 context specs |
| `harness/runtime/tool_call_contract.py` | tool/control action transport | 保持 provider-native 动作传输合同 | 不把 provider transport 写入上下文中枢 |
| `harness/loop/admission.py` | action admission / permit 前置裁决 | 只授权或反馈，不改写模型目标 | denial 进入 ActionFeedback，不变成 hidden context fallback |
| `memory_system/runtime_context_provider.py` | memory hint 事实源 | 输出 low-authority memory context line | conversation continuity / runtime memory 不替代 provider protocol history |
| `runtime/output_stream/public_stream_compiler.py` | public event 投影 | 只发布可见 projection | 不成为 agent context authority |
| `runtime/model_gateway/model_runtime.py` | provider request/response lifecycle | 只在 provider success 后触发 context commit/promotion | failed/cancelled/interrupted response 不封存 current append |
| `runtime/model_gateway/provider_payload.py` | provider payload manifest | 校验 physical lane 与 lifecycle | provider_visible_context_prefix 必须是 confirmed frame replay |
| `frontend/src/lib/api/chatStream.ts` | stream cursor / replay consumer | 恢复可见流和 cursor | 不把前端缓存作为 provider-visible old context |
| `frontend/src/lib/store/runtime.ts` | frontend projection state | 保留断线前可见投影 shell | 不因断线清空 projection；不伪造后端上下文 |
| `README.md` | 设计说明 | 同步最终原则和流程 | 不再描述旧排序函数 |

### 8.1 Clean Cutover 与回滚规则

本计划不采用长期 v1/v2 双跑，也不在 active code 中保留旧主链路作为兼容路径。实施时采用 clean cutover：

```text
1. 先补齐 ContextLineDeclaration / PhysicalContextInputs / commit terminal policy 的静态合同。
2. 再把所有 invocation 切到统一 classify + assemble 链路。
3. 删除 follow-up 私有 physical assembly 和 context contract lane fallback。
4. 删除或改名会暗示旧 authority 的 apply/reorder/annotate API。
5. 最后做真实运行链路验证。
```

允许的回滚方式：

```text
git/service rollback 到实施前版本
恢复上一份可运行构建
保留诊断日志和 storage 数据用于追查
```

禁止的回滚方式：

```text
在 active runtime 中保留旧四段拼接函数
让旧函数作为 fallback 被新链路调用
用 invocation kind 判断走新旧双路径
让 frontend cache 或 memory summary 顶替 provider old context
```

## 9. 验证方案

不新增回归测试文件。验证用代码审查、编译、无文件结构探针和真实运行链路。

### 9.1 静态验证

```text
python -m py_compile changed runtime files
rg annotate_specs_with_physical_context_plan backend
rg _physical_context_order_key backend
rg _single_agent_turn_followup_physical_context_assembly backend
rg provider_protocol_replay_prefix backend
rg "physical_lane_for_spec\\(" backend/harness/runtime/context_contract
rg "physical_lane_for_spec" backend/runtime backend/harness --glob '!**/design_docs/**'
rg "runtime.context_management.physical_context_plan\".*physical_lane_projection" backend/harness/runtime/context_contract
rg "runtime_memory_context.*CONTEXT_MEMORY_PREFIX" backend/runtime/context_management
rg "physical_prefix_frame_user_context_replay.*current_user_intent" backend/runtime/context_management
```

要求：

```text
旧排序 authority 不在 active code
旧 follow-up 手工拼接不在 active code
plan 不再修改 specs
context_contract 不再推断真实 physical lane
physical lane edge authority 不再指向 physical_context_plan
runtime_memory_context 不再声明为 confirmed old context
historical user replay 不再使用 current_user_intent 语义槽
```

### 9.2 结构探针

输入：

```text
static
old replay
current user
runtime memory
tool transcript
dynamic tail
```

期望输出：

```text
global_static_prefix index=1
provider_visible_context_prefix index=2
current_turn_tail index=3..n
never_replay_tail index=n+1
```

并确认：

```text
每个 spec 都有 physical_prefix_lane
每个 spec 都有 context_physical_assembly_index
lane_order 不出现 stable-after-tail violation
```

### 9.3 真实运行验证

涉及运行链路时必须按项目固定端口实测：

```text
frontend: http://127.0.0.1:3000
backend:  http://127.0.0.1:8003
api:      http://127.0.0.1:8003/api
```

场景：

```text
单轮用户请求
tool call + tool observation follow-up
下一轮 initial
断线/恢复后的上下文投影
```

检查：

```text
initial 和 follow-up 共享同一 physical assembly diagnostics
上一轮 confirmed frame == 下一轮 old context
current append 不提前晋升
dynamic tail 不进入 frame
failure / cancel / interrupt 不产生 confirmed frame
frontend 断线重连后只恢复 public projection/cursor，不清空已显示 projection
重复 replay 按 runtime_event_id / projection key 幂等合并
如需让 agent 感知恢复事件，恢复事实以 dynamic recovery line 入中枢
```

## 10. 禁止事项

```text
不允许在插线后排序
不允许在 harness 手工拼四段
不允许系统资产没有线路声明
不允许先插线再按 enabled/disabled 过滤
不允许用 semantic slot 决定 provider physical boundary
不允许用 ledger entry index 全量回放旧上下文
不允许把 current user 当长期历史替代品
不允许让 memory summary 替代 provider protocol history
不允许把 dynamic tail 写入 confirmed old context
不允许 failure / cancel / interrupt 晋升 physical prefix frame
不允许旧用户历史 replay 使用 current_user_intent 语义槽
不允许 frontend replay 生成 provider/model context
不允许为了兼容保留旧主链路
不允许新增 v2 双跑长期兼容路径
不允许新增测试文件来证明结构正确
```

## 11. 预期结果

完成后应达到：

```text
1. 所有上下文线都有明确物理段。
2. 所有系统资产都有线路声明；是否进入本轮上下文由 activation 字段控制。
3. 新增信息线只需声明线路属性，不需要修改四段算法。
4. initial、tool follow-up、observation follow-up 使用同一物理算法。
5. provider-visible ledger 不再拥有 replay 排序权。
6. physical plan 不再拥有修复或排序权。
7. current user、memory、provider history、tool transcript、dynamic control 的语义位置清楚。
8. cache spine 和 provider payload 的诊断能追溯到真实物理顺序。
9. provider success 是唯一 confirmed old context 晋升入口。
10. frontend projection replay 只影响 public projection，不进入 agent provider context。
11. 旧 active 主链路被删除，不存在长期双跑兼容。
```

## 12. 审阅重点

实施前需要确认九件事：

```text
1. 是否接受 PhysicalContextInputs 作为唯一四段输入契约。
2. 是否接受所有 invocation 都必须经过 physical assembler，即使 ledger skipped。
3. 是否接受删除 follow-up 私有 physical assembly，不保留旧兼容主路径。
4. 是否接受每个系统资产必须有 SystemAssetLine，且由 context_line_state 控制是否进入本轮上下文。
5. 是否接受 context contract / physical plan / public projection 都只能做只读诊断或呈现，不能推断、补写或重排 physical lane。
6. 是否接受控制输出端只消费上下文中枢和输出 ActionFeedback，不反向发明上下文线。
7. 是否接受 runtime_memory_context 作为 low-authority current hint，不再作为 confirmed old context。
8. 是否接受 provider success 是 current append 晋升 physical prefix frame 的唯一入口。
9. 是否接受 clean cutover：删除旧 active 主链路，不保留 v1/v2 双跑兼容。
```

确认后才能进入代码实施。
