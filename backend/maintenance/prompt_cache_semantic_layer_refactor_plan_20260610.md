# Prompt Cache 语义分层重构计划（2026-06-10）

## 一、修正后的判断

这次 prompt cache 命中率偏低，不是单纯提示词太长，也不是简单把内容标成 `static` 就能解决。

核心问题是：当前系统把不同语义失效域混进同一个稳定桶里，尤其是把环境身份、环境资源、项目规则、生命周期策略和运行态触发提示一起塞进 `environment_stable`。这会导致一个本应局部变化的运行态信号，反向污染上游稳定层。

因此目标不是寻找“绝对静态层”，而是在语义支撑关系上做层层划分：

```text
上层定义下层成立的前提。
下层只能依赖上层，不能反向改变上层。
缓存层只是语义层在 provider prefix cache 上的投影。
```

## 二、实测证据

### 1. 工具面收窄后仍不合格

最新 code review 实测：

- 报告目录：`storage/runtime_state/prompt_cache_live_tests/code_review_cache_e2e_20260610_172443_ec77c2`
- provider 调用：2 次
- 总命中率：52.26%
- warm 后命中率：53.44%
- stable prefix：18,055 tokens
- session prefix：14,673 tokens
- task prefix：18,055 tokens
- visible tools 已收窄为只读文件/搜索工具
- `tool_index_stable` 已降到约 1,321 tokens

这说明工具列表过大是一个问题，但不是剩余命中率低的主因。

### 2. replay 被错误排除在可复用前缀之外

同一实测中：

- 第 1 次调用 volatile：772 tokens
- 第 2 次调用 volatile：3,810 tokens
- 第 2 次调用包含 7 个 `task_state_replay_entry`
- 每个 replay entry 都标记为：
  - `cache_scope=none`
  - `cache_role=volatile`
  - `prefix_tier=volatile`

但这些 replay entry 的语义并不是“当前瞬态”。它们是已经提交的工具观察和任务事实，是当前判断的证据基础。只要 entry 内容不可变、顺序可确定、source ref 稳定，就应该进入“任务内已提交事实层”，作为 task prefix 的 append-only 可复用部分。

### 3. lifecycle prompt 混入 environment stable

代码路径：

- `backend/harness/runtime/environment_prompt_controller.py`
  - `_lifecycle_prompt_selection_for_invocation()` 根据 invocation、可见工具、observation、subagent result、memory、compaction 等运行态信号选择 lifecycle prompt。
- `backend/prompt_composition/section_renderer.py`
  - `render_environment_instruction()` 把 environment prompt 和 lifecycle prompt 拼成同一个环境说明。
- `backend/harness/runtime/compiler.py`
  - task execution 的 `environment_stable` source_ref 同时包含 environment refs 和 lifecycle refs。

结果是：例如工具观察、subagent 返回、memory 信号出现时，`environment_stable` 会变化。这个变化的语义属于运行阶段 overlay，不属于环境身份或环境资源边界。

## 三、目标语义层

新的主轴不是 `static/session/task/volatile`，而是语义支撑层。

| 语义层 | 作用 | 失效条件 | Provider cache 投影 |
| --- | --- | --- | --- |
| `L0_provider_protocol` | provider/model 协议、action JSON 协议、全局运行包 | 模型、provider、协议版本、runtime pack 版本变化 | provider global |
| `L1_runtime_foundation` | 通用安全、真实性、当前请求优先、注入防护、用户资产保护 | runtime 基础规则版本变化 | provider global 或 session |
| `L2_environment_identity` | 当前环境身份、环境资源边界、存储边界、项目指令权威内容 | 环境切换、项目指令内容变化、环境资源配置变化 | session |
| `L3_environment_work_discipline` | 环境专属工作纪律，例如 coding/office 的全套工作规则 | 环境规则版本变化 | session |
| `L4_agent_profile` | agent 身份、人格、职责、可交付风格 | agent/profile/personality 变化 | session |
| `L5_action_surface` | action schema、operation ceiling、工具 index、工具 schema 指纹 | 可见动作、工具权限、工具 schema 或 ceiling 变化 | task |
| `L6_task_contract` | 用户目标、任务合同、artifact scope、验收标准、计划锁 | task contract 或用户 steering 修订合同 | task |
| `L7_bound_task_context` | 任务绑定上下文：计划书、关键文件、读取窗口、编辑目标、产物 refs、恢复策略 | 绑定清单变化、文件内容 hash 变化、计划修订、关键窗口过期 | task |
| `L8_task_runtime_boundary` | 本次 task run 的执行边界、动态投影中稳定的权限/上下文摘要 | task run 边界、权限投影、稳定 runtime projection 变化 | task |
| `L9_committed_replay` | 已提交 observation、工具结果摘要、不可变 evidence entry | 新 entry append、旧 entry 内容变更应视为错误 | task append-only prefix |
| `L10_current_volatile` | 当前最新状态、pending steer、未提交观察、最近失败、当前进度 | 每轮变化 | volatile suffix |

关键约束：

1. 上层不能引用下层事实。
2. session 层不能引用 task id、task contract、observation、runtime instance id。
3. task stable 层不能引用每轮变化的 attempt、pending status、最新未提交观察。
4. append-only replay 只能增长，不能重写旧 entry。
5. lifecycle prompt 要按语义拆分：基础阶段策略可稳定，触发态恢复提示必须是 overlay，不能污染 environment identity。
6. `bound_task_context` 只绑定任务语义必需材料，不收集普通历史噪声；它记录文件、计划和 artifact 的 ref、hash、可见窗口、恢复方式和失效条件。

## 四、当前结构问题

### 1. `cache_scope` 太粗

当前 `backend/prompt_composition/planner.py` 用 `cache_scope` 推导：

```text
static/global -> provider_global
static_environment/session -> session
task/task_stable -> task
none/volatile -> volatile
```

这个模型只能描述缓存范围，不能表达语义层，也不能表达“同属 session 但失效域不同”。因此 `environment_stable` 内部混层后，planner 无能力发现问题。

### 2. `environment_stable` 承担了多种权威

当前 `environment_stable` 同时承担：

- 环境身份。
- 环境资源边界。
- 项目 AGENTS 指令。
- coding/office 环境规则。
- lifecycle prompt。
- prompt mount plan 的模型可见部分。

这些内容并非同一失效域，不能放在一个稳定段里。

### 3. lifecycle selection 是动态的，但渲染位置是稳定的

`_lifecycle_prompt_selection_for_invocation()` 根据运行态信号选择 prompt，这个逻辑本身可以保留。

错误在于：被选中的 lifecycle prompt 被合并进 `environment_stable`。正确做法是：

- 恒定 lifecycle policy base：进入稳定层。
- 由 observation、subagent result、memory write、compaction、pending steer 触发的 overlay：进入独立 lifecycle overlay 层。
- 如果 overlay 每轮都会变化，就进入 volatile tail；如果 overlay 在 task 内可预测且从第一轮就确定，则可以稳定化。

### 4. replay 的语义和缓存角色冲突

`_task_state_replay_message_specs()` 明确写着 append-only，但仍标成 volatile：

```text
cache_impact = volatile_suffix_append_only
runtime_fragment_role = append_only_task_state_evidence
```

append-only evidence 不应该和 current volatile state 合并治理。它应该成为 `L9_committed_replay`。

## 五、目标装配顺序

Task execution 目标顺序：

```text
1. global_runtime_protocol
2. runtime_foundation
3. action_schema
4. environment_identity
5. environment_work_discipline
6. lifecycle_policy_base
7. personality
8. agent_profile
9. action_surface / tool_index
10. artifact_scope
11. task_contract
12. bound_task_context
13. task_runtime_boundary
14. committed_task_replay_prefix
15. lifecycle_trigger_overlay
16. current_volatile_task_state
17. user_steering_updates
18. provider params / response format
```

说明：

- `lifecycle_policy_base` 是稳定阶段规则，例如 action selection、verification gate、finalization。
- `lifecycle_trigger_overlay` 是由当前 observation/subagent/memory/compaction/pending steer 触发的恢复或整合提示。
- 如果某类 overlay 在 invocation 开始前就能由 action surface 稳定决定，应放入 base；如果依赖 observation，就不能进 environment stable。
- `bound_task_context` 是任务语义上下文的绑定清单，不是完整文件内容仓库。模型可见部分应该是短清单、必要窗口摘要和 rehydration 指令；完整内容由 read/rehydration 工具恢复。
- `committed_task_replay_prefix` 必须位于 current volatile 之前，且旧 entry 不可重写。

## 六、Bound Task Context 目标层

`bound_task_context` 用于补齐 Codex/Claude 类 coding agent 的“附件绑定”能力。它把任务需要持续携带的文件、计划和产物从普通历史观察中提升为一等任务上下文。

目标对象建议：

```text
TaskRun
-> BoundTaskContext
   -> plan_refs
   -> task_file_refs
   -> read_windows
   -> edit_targets
   -> artifact_refs
   -> rehydration_refs
   -> restore_policy
```

模型可见投影只包含：

- 计划 ref、计划状态、是否 implementation locked。
- 关键文件路径、用途、最近读取窗口、content hash、stale 状态。
- 已编辑或待编辑目标文件。
- 与验收有关的 artifact refs。
- compact/resume 后如何恢复精确内容。

不包含：

- 所有读取过的文件全文。
- 普通搜索噪声。
- 未确认的工具猜测。
- 当前 pending steer。
- 每轮变化的 executor status。

和现有结构的关系：

- `TaskRunContract.external_plan_ref` 是计划绑定来源之一。
- `FileStateAuthorityStore` 是文件状态来源之一。
- `DynamicContextProjection.context_refs/artifact_refs` 是上下文和产物引用来源之一。
- `task_state_replay_entry` 记录已发生事实，但不应该承担“哪些文件/计划需要持续绑定”的职责。

## 七、落地计划

### 阶段 1：增加语义层元数据，不改变模型行为

修改：

- `backend/prompt_library/models.py`
- `backend/prompt_library/assembly.py`
- `backend/prompt_composition/models.py`
- `backend/prompt_composition/planner.py`
- `backend/harness/runtime/prompt_segment_plan.py`

目标：

- 为 PromptResource / PromptSection / PromptCompositionSlot / PromptSegmentPlanSegment 增加 `semantic_layer` 或等价字段。
- 保留现有 `cache_scope/cache_role/prefix_tier`，但不再让它们承担语义分类。
- manifest 输出 semantic layer sequence、semantic invalidation domain、cache projection。

验证：

- 结构测试：同一 segment 同时有 semantic layer 与 cache projection。
- 结构测试：session semantic layer 不允许携带 task id / observation / runtime instance fields。

### 阶段 2：拆开 environment 与 lifecycle

修改：

- `backend/prompt_composition/section_renderer.py`
- `backend/harness/runtime/compiler.py`
- `backend/harness/runtime/environment_prompt_controller.py`

目标：

- `render_environment_instruction()` 只渲染环境身份、环境资源和环境工作纪律。
- 新增 lifecycle 独立渲染函数，至少拆成：
  - `lifecycle_policy_base`
  - `lifecycle_trigger_overlay`
- task execution 不再把 lifecycle refs 拼入 `environment_stable`。
- `environment_stable` 的 source_ref 不再包含 observation/subagent/memory/compaction 触发出来的 refs。

验证：

- code review task 第 1 次到第 N 次调用，`environment_identity` / `environment_work_discipline` hash 不因 observation 增加而变化。
- lifecycle overlay 的变化只影响 overlay 层或 volatile suffix。

### 阶段 3：把 committed replay 接入 task prefix

修改：

- `backend/harness/runtime/compiler.py`
- `backend/harness/runtime/dynamic_context/task_state_projector.py`
- `backend/runtime/model_gateway/provider_payload.py`
- `backend/prompt_composition/manifest.py`

目标：

- 将已提交、不可变、已排序的 replay entry 标记为：
  - semantic layer：`L8_committed_replay`
  - cache_scope：`task`
  - cache_role：`session_stable`
  - prefix_tier：`task`
- 仍把最新未提交状态留在 `volatile_task_state`。
- provider payload 的 selected prefix 可以覆盖 committed replay 中已经稳定的部分。

约束：

- replay entry 必须有稳定 source ref，例如 observation_ref 或 entry hash。
- 如果旧 entry 内容变化，诊断必须报错，不能静默当作新缓存。
- user steering 未消费队列不能混入 replay stable。

验证：

- 构造 3 轮 replay：旧 entry hash 保持不变，新 entry append 后 task prefix boundary 后移。
- 若旧 replay entry 被改写，结构测试应失败。

### 阶段 4：新增 bound task context 绑定层

修改：

- `backend/harness/loop/task_lifecycle.py`
- `backend/harness/runtime/dynamic_context/manager.py`
- `backend/runtime/memory/file_state_store.py`
- `backend/harness/runtime/compiler.py`
- 如需独立权威对象，新增 `backend/harness/runtime/bound_task_context.py`

目标：

- 从 task contract、file state、artifact refs、rehydration refs 构建 `BoundTaskContext`。
- 在 task execution prompt 中新增 `bound_task_context` segment，位于 `task_contract_stable` 之后、`task_runtime_boundary_stable` 之前。
- `bound_task_context` 使用 task prefix，内容以短清单和恢复指令为主，不塞全文。
- compact/resume 时优先恢复 `bound_task_context` 指向的关键文件窗口，而不是按最近历史消息猜。

验证：

- 任务绑定计划 ref 后，prompt 中出现稳定 plan binding，且不重复进入 volatile state。
- read_file 后，关键读取窗口进入 bound context，包含 path、range、hash、rehydration plan。
- 文件 stale 或 hash 改变时，bound context 标记需要重新读取，不能允许模型直接编辑旧窗口。
- bound context 不包含普通搜索噪声和 unrelated artifact refs。

### 阶段 5：重跑真实 code review cache 实测

命令：

```powershell
python backend/scripts/live_five_floor_dungeon_prompt_cache_e2e.py --scenario code_review --max-provider-calls 6
```

验收：

- 工具面仍保持 operation ceiling 后的只读工具。
- `environment_identity` / `environment_work_discipline` 稳定。
- `task_prefix_tokens` 随 committed replay 增长。
- current volatile 占比显著下降。
- 代码审核类任务 warm 后命中率应接近或超过 90%，除非模型输出或 provider params 本身产生大量不可缓存尾部。

## 八、不做的事

- 不改 `graph-node`。
- 不为了命中率删除必要任务事实。
- 不把当前 volatile 状态伪装成 stable。
- 不用旧语义测试保护旧模板。
- 不通过减弱断言、跳过测试或硬编码 provider 结果制造通过。

## 九、需要用户确认的实施边界

这会触碰 runtime prompt 装配、prompt composition、provider payload cache boundary 和 task replay 投影，属于核心链路重构。

建议按上面四个阶段执行。第一阶段只加语义层元数据和诊断，不改变模型实际 prompt；第二、三阶段才改变模型可见 segment；第四阶段跑真实实测。
