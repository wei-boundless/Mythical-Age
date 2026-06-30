# Agent Control Network Architecture Cleanup Plan

创建日期：2026-06-30

状态：执行中。用户已确认开始实施；本文作为“大清洗 / 大改革”主计划，实施必须继续以 harness runtime spine 为唯一运行主干。

2026-06-30 harness 审查修订：`harness` 已经存在真实运行脊柱，本文中的 `AgentControlNetwork` 不再表示新的后端运行中枢或新的运行权威，只表示 `/agent-network` 页面需要读取的只读 runtime topology projection / inspection facade。真实主脊柱以 `SingleAgentRuntimeHost`、`AgentRuntimeServices`、`RuntimeGateway`、`RuntimeEventLog`、`run_single_agent_turn`、`RuntimeCompiler`、`OutputCommitAuthority` 和 `TurnMemoryStore` 为准。

2026-06-30 Phase 5 实施更新：普通 single-agent turn 的恢复权威已收口到 `TurnMemoryRecoveryContext`。`runtime_facade.py` 不再把非终态 continuation record 写入 `session_context["recoverable_work"]`，`request_facts.py` 已移除 `recoverable_work_candidate`，`packet_assembler.py` 不再因为旧 continuation record 打开 `resume_task_recovery` 动作面，`compiler.py` 不再投影 `recoverable_work` 模型可见动态段。`resume_task_recovery` 动作类型和 continuation recovery boundary 仍保留在 task recovery/control 体系中，不作为普通 turn 恢复入口。

2026-06-30 Phase 5 命名收口：task recovery/control 的模型动作已从旧 `resume_recoverable_work` 统一为 `resume_task_recovery`，句柄对象统一为 `task_recovery_resume`。普通 turn 恢复继续由 `TurnMemoryRecoveryContext` 表达，并在模型可见 payload 中声明 `forbidden_action=resume_task_recovery`。

2026-06-30 turn/task 关系校正：本计划中的“分离”只表示恢复权威分离，不表示 task 脱离 turn 生命周期。`turn` 仍是用户输入、模型裁决、动作授权和恢复接入的节拍；`task` 是由 turn 申请或重新接入的持久工作资源。task 可以跨 turn 存活，但每次启动、恢复、控制、继续调度都必须绑定当前 turn，并通过当前 turn 的 action surface 与 runtime boundary 获得授权。

## 1. 目标裁决

本轮不是在旧系统上继续加功能，而是把单 agent runtime 的控制网络收束成一条可观测、可诊断、可恢复、可删除旧分支的权威链路。

目标链路：

```text
RequestFacts
-> RuntimeBoundary / TurnOperatingContract
-> ContextCandidates
-> ContextPipeline
-> PhysicalContextPlan / PhysicalContextAssembler
-> ModelRequestBuilder
-> ProviderPayloadManifest
-> ProviderCacheBus / PrefixCacheHealth
-> ProviderVisibleLedger / PhysicalPrefixFrameLedger
-> TurnMemoryStore
-> TurnMemoryRecoveryContext
-> next turn RuntimeBoundary
```

本计划中的诊断/展示命名使用：

```text
RuntimeTopologyProjection
RuntimeTopologyEdge
ConnectionContract
ControlSignal
FeedbackRoute
```

`AgentControlNetwork` 只作为页面和用户可见概念保留；代码层优先沿用已有 `harness` runtime/context-contract/inspection 命名。

禁止把比喻词写进代码命名。用户所说的“神经系统”在工程上落为：每条控制线必须有 producer、payload identity、authority、transport/store、consumer、failure route、diagnostics。

## 1.1 Turn / Task 生命周期不变量

成熟单 agent runtime 必须保持以下不变量：

1. `turn` 是唯一交互节拍。所有用户输入、模型动作选择、权限裁决、工具动作、task 申请、task 控制和输出提交都必须落在明确的 `turn_id` 上。
2. `task` 是跨 turn 的持久工作资源，不是第二条对话主链。task 只能保存目标、计划、todo、恢复点、验收边界和执行状态；它不能绕过当前 turn 自行解释用户意图。
3. `request_task_run` 表示当前 turn 申请持久任务资源；runtime 生成 `task_run_id` 后必须把当前 turn 绑定到该 task。
4. `resume_task_recovery` 表示当前 turn 重新接入已存在 task 的恢复边界；它必须校验 `task_run_id` 与 `continuation_id`，并在调度前调用当前 turn/task 绑定。
5. `TurnMemoryRecoveryContext` 只恢复普通 turn 的热账本状态；它不能启动或恢复 task。模型可见 payload 必须继续声明 `forbidden_action=resume_task_recovery`。
6. task execution 可以执行长任务步骤，但其结果、暂停、失败、恢复包和用户可见输出仍要回写到 runtime event log、task run state 和关联 turn refs，不能形成独立记忆链。

因此，本轮架构目标不是“普通 turn 与 task 分家”，而是：

```text
current turn decision
-> action permit
-> task resource / task recovery when explicitly authorized
-> bind current turn to task_run
-> execute / record / recover through runtime spine
-> next turn re-enters through RuntimeBoundary
```

## 2. 清洗标准

一个模块或分支只有在目标链路中拥有明确 current owner，才允许保留。

必须清理或降级的情况：

1. 用字符串、标题、kind、cache_role 猜测控制域。
2. 作为前端展示，却伪装成后端事实权威。
3. 与 `ProviderCacheBus` / `prefix_cache_health` 并行解释缓存健康。
4. 与 `TurnMemory` 并行决定 turn 间恢复。
5. 以兼容、fallback、bypass 为名保留旧运行路径。
6. 只为旧字段、旧测试、旧展示形态存在，不能被 runtime 控制网络诊断。

保留标准：

```text
有唯一 authority
有明确输入输出契约
能被 runtime topology projection 只读投影
失败时进入明确 FeedbackRoute
不会重新决定上游或下游语义
```

## 3. 当前主干事实

### 3.1 已经存在的正确主干

| 主干模块 | 当前职责 | 裁决 |
| --- | --- | --- |
| `backend/runtime/context_management/context_pipeline.py` | candidate -> capability filter -> provider-visible ledger -> physical plan | 保留，作为 context pipeline 主干 |
| `backend/runtime/context_management/physical_context_plan.py` | 分配四段物理 lane：`global_static_prefix`、`provider_visible_context_prefix`、`current_turn_tail`、`never_replay_tail` | 保留，作为物理 lane authority |
| `backend/runtime/context_management/physical_context_assembler.py` | 唯一拼接顺序：static prefix -> confirmed old frame -> current append -> dynamic tail | 保留，作为 physical splice authority |
| `backend/runtime/context_management/context_prefix_identity.py` | `context_prefix_identity`，拆分 logical identity、content hash、provider serialized hash、cache expectation | 保留，继续贯穿下游 |
| `backend/runtime/model_gateway/provider_payload.py` | `ProviderPayloadManifest`，记录 provider request bytes、transport contract、physical cache spine | 保留，作为 provider transport authority |
| `backend/runtime/prompt_accounting/prefix_cache_health.py` | expected prefix coverage / under-read / first missing identity 的核心算法 | 保留，作为 cache verdict authority |
| `backend/runtime/prompt_accounting/provider_cache_bus.py` | 把 provider usage 写成 UI/API 可读 cache log | 保留，作为前端缓存日志 authority |
| `backend/runtime/turn_memory/turn_memory_models.py` | turn 热账本：provider refs、manifest refs、frame、draft/final、tool rounds、commit/recovery state | 保留，作为 Present/Future hot ledger |
| `backend/runtime/turn_memory/turn_memory_recovery_context.py` | 从 TurnMemory 选择可恢复 turn，输出恢复上下文 | 保留，作为 recovery facade |

### 3.2 已经接通但还没完成清洗的线

| 线 | 证据 | 当前问题 | 目标动作 |
| --- | --- | --- | --- |
| runtime facade -> TurnMemory recovery -> compiler | `runtime_facade.py` 调用 `build_turn_memory_recovery_context()`；`compiler.py` 投影 `turn_memory_recovery` | 2026-06-30 已移除普通 turn 的 `recoverable_work` 模型可见投影和动作面触发 | TurnMemory 拥有恢复决策权；旧 continuation 只保留近期结果、task recovery boundary 或诊断 |
| ProviderPayload -> PrefixCacheHealth -> ProviderCacheBus -> API/frontend | `model_runtime.py` 调用 `publish_provider_cache_usage()`；`api/tokens.py` 输出 `provider_cache_log`；`ChatPanel.tsx` 读取 under-read；`app_runtime.py/microcompact.py` 已改读 prefix health；`prefix_state` 已承接 previous/continuity/reset | preflight cache plan 已拆到 `cache_plans.jsonl`，provider result 只进入 `provider_cache_bus.jsonl` | 旧 baseline/stability/cache result 双写已退出 active path |
| Provider message replay contract | `physical_context_assembler.py` 生成 physical frame replay；`provider_message_replay_contract.py` 判断 byte-preservation | 2026-06-30 已删除旧 protected-context guard / bypass 表达 | 只允许 physical prefix frame replay 与 provider protocol replay 触发 byte-identical preservation |
| `/agent-network` 页面 | `frontend/src/app/agent-network/page.tsx` 已有可视化 | 静态 `CORE_NODES` / `CORE_EDGES` 是前端自造权威 | 后端只读 runtime topology projection 成为唯一 core graph 展示数据源 |

## 4. 结构性问题

### P1. ContextContract 字符串启发式分类已退出主链路

证据：

```text
backend/harness/runtime/context_contract/authority_rules.py
backend/harness/runtime/context_contract/manifest.py
```

旧 `classify_context_spec()` 根据 `kind`、`cache_role`、metadata 文本推断：

```text
agent_use_contract
commit_policy
replay_policy
cache_tier
```

问题：

- 它把“看起来像 memory/evidence/runtime/tool”的文本当成 authority。
- `cache_role` 默认 `volatile` 会污染判断。
- 它可以做 diagnostics，但不该继续决定 AgentControlDomain。

当前动作：

- `ContextContractNode` 已使用显式 `agent_domain`、`control_signal`、`feedback_route`、`connection_contract_ref`、`control_layer`、`time_scope`、`physical_lane`。
- `authority_rules.py` 只从 registry、segment policy、physical lane 和 prefix identity 归一化 contract，不再输出 `semantic_kind/semantic_layer/semantic_time`。
- `authority_rules.py` 不再通过 `declaration.source_kind` 映射 `agent_domain`；domain 只来自显式 metadata、registry capability、provider transport lane 或四段 section。
- `prompt_composition.slot_policy` 不再维护 `source_kind -> layer/dynamic_tier/authority_class` 旁路表；prompt slot 的 layer 与 dynamic tier 只读 kind registry、kind-specific policy 和缓存 section 兜底，`source_kind` 只保留为来源身份。
- `context_segment_policy.py` 不再通过 `prompt_assembly_dynamic_tier/dynamic_tier` 或 `cache_role=session_stable/cacheable_prefix` 反推四段 section；所有 registry kind 已补齐显式 section，未知段只能走调用方 `default_section` 或显式 metadata。
- 缺少显式 contract 时报告 `missing_connection_contract`，不再靠旧 semantic 层级猜主链路。

### P1. 前端静态图是假权威

证据：

```text
frontend/src/app/agent-network/page.tsx
CORE_NODES
CORE_EDGES
localStorage supplements
```

问题：

- 页面可以描述真实方向，但现在没有后端 producer。
- `connected / weak / planned` 是手写结论，不能证明真实 runtime 连接。
- 用户补充存在 localStorage，不能参与系统控制判断。

目标动作：

- 实施后端只读 runtime topology projection。
- 前端 core graph 只读后端 API。
- `localStorage` 只作为用户注释层，不能覆盖 core node/edge authority。
- 2026-06-30 Phase 1/2 已删除前端静态 `CORE_NODES` / `CORE_EDGES` core authority；页面加载失败时显式报错，不用静态图伪装成功。

### P1. 缓存健康旧账本双写已收口，cache plan/result 已拆分

证据：

```text
backend/runtime/model_gateway/model_runtime.py
  ledger.record_prefix_state(prefix_state_record)

backend/runtime/prompt_accounting/ledger.py
  PREFIX_STATE_FILE
  record_prefix_state(...)
  reset_prefix_state(...)

backend/bootstrap/app_runtime.py
  cached_tokens > 0 -> warm
```

问题：

- `ProviderCacheBus` 已经是正确缓存日志入口，旧 baseline/stability 已退出 active request 写入。
- `cached_tokens > 0` 不再用于判断 warm。
- 总 hit rate 只能做辅助指标，不能裁决 prefix health。
- `cache_plans.jsonl` 只表达 preflight local cache plan；provider result 不再回写 cache plan。

目标动作：

- `ProviderCacheBus.summary.current_prefix_covered` 和 `latest_under_read_tokens` 成为 UI/cache health 唯一健康入口。
- `prompt_cache_baselines.jsonl` 和 `prompt_stability.jsonl` 已退出新写入/读取路径；`prefix_state.jsonl` 是 previous/continuity/reset 权威。
- `app_runtime.py` 改读 `ProviderCacheBus`，不再用 `cached_tokens > 0` 判断 warm。
- 保留旧 jsonl 只读历史迁移，不作为 active authority。
- provider-visible ledger 的 turn 归属只读取 provider success 确认时写入的 `confirmed_turn_id`；`confirmed_by_request_id` 只用于 provider request 审计，不再承担 turn 身份解析。
- prefix identity 的 replay 生命周期只读显式 replay contract，不再通过 physical frame kind/source 字符串猜测；provider protocol replay 和 physical frame replay 分开表达，避免缓存身份混线。
- historical-only 可见性只由显式 visibility/replay flags 表达，不再由 `semantic_commit_class` 前缀族推断，避免语义类名变成隐藏控制开关。

### P1. TurnMemory 与 continuation recovery 双权威风险已收口

证据：

```text
backend/harness/entrypoint/runtime_facade.py
backend/harness/runtime/compiler.py
backend/harness/continuation/selector.py
backend/harness/continuation/record.py
```

当前情况：

- `turn_memory_recovery` 已接入 `session_context`，这是正确主干。
- `recoverable_work` 不再由 `runtime_facade.py` 写入普通 turn `session_context`。
- `compiler.py` 不再把 continuation record 投影成模型可见 volatile payload。
- `packet_assembler.py` 不再根据旧 continuation record 开放 `resume_task_recovery` 普通 turn 动作面。
- continuation record 仍保存 `visible_assistant_prefix`，但该字段只留在 selector/record 元数据中；当前 compiler 不读取它，也不把它作为 active recovery prompt source。

目标动作：

- `TurnMemoryRecoveryContext` 作为恢复决策唯一入口。
- continuation record 降级为 read-only recent outcome / task recovery boundary / diagnostics。
- `visible_assistant_prefix` 不进入 active model-visible recovery authority。
- 搜索确认 `interrupted_turn_work` 不存在普通 single-agent 恢复入口；`visible_assistant_prefix` 只在 `harness.continuation.selector/record` 内部生成和保存。

### P2. Provider message replay contract 已收口

证据：

```text
backend/runtime/context_management/provider_message_replay_contract.py
backend/runtime/context_management/context_pipeline.py
backend/harness/runtime/compiler.py
```

当前情况：

- provider message byte-identical replay 必须保留。
- 2026-06-30 已删除旧 shared protected-context helper，统一由 `provider_message_replay_contract` 判断 byte-preservation。
- 合法 replay contract 只有 physical prefix frame replay 与 provider protocol replay。
- 2026-06-30 继续收口：`context_pipeline.sealed_provider_visible_replay_spec()`、`physical_context_assembler._current_append_specs()` 和 `context_segment_policy` replay section 分类已停止自建 replay 条件；sealed 判断、capability filter、section 分类、current append 分流、compiler sanitizer 和 materializer byte-preserve 均消费同一个 `provider_message_replay_contract` owner。
- `content_source` 不再是 provider protocol replay 授权字段；它只能描述来源，不能单独触发 byte-preserve replay。

目标动作：

- `PhysicalPrefixFrameLedger` / `PhysicalContextAssembler` 生成 confirmed frame replay metadata。
- provider protocol replay 只表达同 turn provider transcript byte-preservation。
- compiler/materializer 只能执行“保留 provider message bytes”这一件事，不能扩大为权限或能力旁路。

### P2. `semantic_*` 作为目标架构语言需要退场

证据：

```text
backend/harness/runtime/context_contract/nodes.py
backend/harness/runtime/context_contract/diagnostics.py
backend/harness/runtime/context_contract/inspection_payload.py
frontend/src/lib/api/types.ts
```

问题：

- active `ContextContractNode` 已移除 `semantic_kind/layer/time`。
- 目标系统表达 agent 控制域、物理 lane、时序状态、连接契约，而不是泛化的 semantic 命名。

目标动作：

- active inspector 以 `agent_domain`、`control_layer`、`time_scope`、`control_signal`、`feedback_route` 为中心。
- 剩余 `semantic_*` 只允许出现在历史研究、graph semantic relation 或 semantic compaction 等独立领域；不能作为 runtime control contract 主字段。

## 5. 目标 Authority 表

| File/module | 当前职责 | 隐藏决策/风险 | 目标层 | 动作 |
| --- | --- | --- | --- | --- |
| `context_pipeline.py` | 上下文候选过滤和物理组装入口 | provider message replay contract 已收口 | normalize/retrieve/assemble | 保留，replay contract 只保留 provider message bytes |
| `physical_context_plan.py` | 四段 lane 分配和排序 | 无明显重复权威 | assemble | 保留，暴露到只读诊断投影 |
| `physical_context_assembler.py` | confirmed frame replay + current append splice | confirmed frame 缺失时 fail-closed 需要展示 | assemble/recover | 保留，诊断接入 network |
| `context_prefix_identity.py` | canonical prefix identity | 需贯穿所有展示和 ledger | normalize/record | 保留并扩散 |
| `provider_payload.py` | provider bytes / transport contract | `prefix_family` 仍大量存在，需确保只作诊断 | assemble/record | 已增加 ContextContract contract refs；继续保留 |
| `prefix_cache_health.py` | cache verdict 核心算法 | 无明显重复权威 | decide diagnostics | 保留，作为唯一 cache health 算法 |
| `provider_cache_bus.py` | provider cache log API | summary 仍包含 hit_rate，需降低权重 | present/record | 保留，前端只读 cache verdict |
| `ledger.py` baseline/stability | legacy prefix state 组件 | active 双写、双账本 | record legacy | 迁移后停止新写 |
| `model_runtime.py` prompt stability/baseline 写入 | 预检与 provider result 双写 | 同 request 多状态解释 | execute/record | 分阶段删除旧写入 |
| `authority_rules.py` | ContextContract 标准字段适配 | 旧 source_kind domain 映射会重复决定 agent 控制域 | diagnostics / contract normalize | 已删除 source_kind domain mapping；domain 只看 explicit metadata、registry capability、provider transport lane 和四段 section |
| `prompt_composition/slot_policy.py` | prompt slot 执行投影 | 旧 source_kind 表会绕过 registry 再决定 layer/dynamic tier | assemble projection | 已删除 source_kind layer/dynamic/authority 旁路表；registry 补齐缺失 layer/capability 声明 |
| `context_segment_policy.py` | Context segment section/cache/replay policy | 旧 dynamic_tier/cache_role 反推 section 会让派生投影和缓存角色变成物理段权威 | normalize / policy projection | 已删除 dynamic_tier/cache_role section inference；registry kind 全部显式 section |
| `manifest.py` | ContextContract nodes/edges | 旧风险是只生成 agent-visible order edge | assemble diagnostics | 已升级为 order / physical lane / provider payload / cache health connection contract |
| `runtime_facade.py` continuation + turn_memory | runtime 调度入口 | `recoverable_work` 与 TurnMemory 双权威已清理 | observe/dispatch | 保留调度；旧 continuation 不再写入普通 turn active recovery context |
| `compiler.py` volatile payload 投影 | 模型可见 runtime state | 旧 continuation recovery 投影已删除 | assemble/present | 只投影 TurnMemory recovery 权威 |
| `frontend/src/app/agent-network/page.tsx` | 控制网络页面 | 静态 core graph 假权威 | present | 改为后端 API，只保留注释层 |
| `bootstrap/app_runtime.py` cache temperature | 应用运行态摘要 | 旧 `cached_tokens > 0` warm 口径已清理 | present diagnostics | 已改读 `ProviderCacheBus.current_prefix_covered / latest_under_read_tokens / latest_prefix_health.verdict` |

## 6. 分阶段实施计划

### Phase 0：锁定主干和删除边界

涉及文件：

```text
backend/runtime/context_management/design_docs/execution_plans/agent_control_network_backend_plan_20260630.md
backend/runtime/context_management/design_docs/execution_plans/agent_control_network_architecture_cleanup_plan_20260630.md
```

动作：

- 确认本计划是 `agent_control_network_backend_plan_20260630.md` 的清洗扩展。
- 明确本轮只处理单 agent runtime 控制网络，不重构 `graph_system` 多 agent 图执行。
- 明确不新增测试文件。

完成标准：

```text
所有后续代码改动都能对应到本计划的 authority 表
没有“为了兼容先留着”的无期限分支
```

### Phase 1：落地基于 harness 的只读 runtime topology projection

涉及文件：

```text
backend/harness/runtime/context_contract/inspection_payload.py
backend/harness/runtime/context_contract/diagnostics.py
backend/api/agent_control_network.py
backend/app.py
```

动作：

- 扩展现有 context contract inspection/diagnostics，或在同目录新增纯只读 projection helper。
- projection 只能读取 `SingleAgentRuntimeHost`、`AgentRuntimeServices`、`RuntimeGateway`、`RuntimeEventLog`、`TurnMemoryStore`、`ProviderCacheBus` 等现有主干。
- 输出固定真实 node/edge 集合，每条 edge 包含：

```text
producer
payload_schema
payload_identity
authority
transport_or_store
consumer
failure_route
diagnostics_key
status
```

- `GET /api/agent-control-network` 返回设计态网络。
- `GET /api/agent-control-network/session/{session_id}` 返回 session evidence：

```text
TurnMemory session projection
ProviderCacheBus latest summary
Context recovery package status
Physical frame/cache spine summary
```

完成标准：

```text
后端能证明每条 core edge 的 source/target/authority
runtime topology projection 只读，不写 ledger、不改 prompt、不改 runtime
```

### Phase 2：前端从静态图切到后端权威

涉及文件：

```text
frontend/src/lib/api/types.ts
frontend/src/lib/api/agentNetwork.ts
frontend/src/app/agent-network/page.tsx
frontend/src/styles/09-agent-network.css
```

动作：

- 增加 API client 和类型。
- 页面加载后端 graph。
- 删除前端 `CORE_NODES` / `CORE_EDGES` core authority。
- localStorage supplements 改为 annotation layer：

```text
不能覆盖 core node
不能覆盖 core edge
不能改变 status/authority
只能附加用户备注
```

完成标准：

```text
/agent-network 的节点和连线来自后端
前端不再裁决 connected/weak/planned
```

### Phase 3：ContextContract 从 heuristic 升级为显式契约

涉及文件：

```text
backend/harness/runtime/context_contract/nodes.py
backend/harness/runtime/context_contract/manifest.py
backend/harness/runtime/context_contract/diagnostics.py
backend/harness/runtime/context_contract/inspection_payload.py
backend/harness/runtime/context_contract/authority_rules.py
```

动作：

- `ContextContractNode` 保持当前 manifest schema，补齐标准控制字段：

```text
agent_domain
agent_role
control_layer
time_scope
control_signal
feedback_route
physical_lane
cache_expectation
connection_contract_ref
provider_payload_segment_ref
```

- `manifest.py` 从显式 metadata / segment policy / prefix identity 构建 contract。
- `authority_rules.py` 不再通过 kind 字符串包含关系猜控制域；它只消费 registry、segment policy、physical lane 和 prefix identity，并把缺失字段报告到 diagnostics。
- `ContextContractEdge` 输出 `edge_id/payload_identity/payload_schema/authority/transport_or_store/consumer/failure_route/cache_expectation/connection_contract_ref/physical_lane/control_signal`。
- `manifest.py` 输出 `agent_visible_order`、`physical_lane_projection`、`provider_payload_binding`、`cache_health_binding`。
- `diagnostics.py` 校验 edge endpoint、authority、payload identity、payload schema、connection contract 和 provider/cache target。
- `inspection_payload.py` 主分组切到 `agent_domain/control_signal/time_scope/physical_lane/connection_contract_ref`，并增加 edge_kind / edge authority / edge physical lane / edge connection contract 分组。
- `compiler.py` 输出 `context_contract_inspection`，不再使用 `semantic_space_inspection` 作为新链路入口。

状态：

```text
2026-06-30 已完成主链路：
- ContextContractNode 已补齐标准控制字段。
- authority_rules.py 已移除 kind/cache_role 字符串启发式主分类。
- authority_rules.py 已移除 declaration.source_kind -> agent_domain 映射；runtime/task/tool/memory/evidence domain 由 registry capability 或物理 section 表达。
- prompt_composition.slot_policy 已移除 source_kind -> layer/dynamic_tier/authority_class 旁路表；显式 registry dynamic_tier 优先于缓存稳定性兜底。
- context_segment_policy.py 已移除 prompt_assembly_dynamic_tier/dynamic_tier 与 cache_role 对 section 的反推；未知 stable cache 不再进入 static_prefix，未知 dynamic_tier 不再改写物理段。
- harness.runtime.compiler 的 dynamic context metadata validation 不再通过 `kind.startswith("dynamic")` 判断动态段；只读 `cache_role=volatile` 或 ContextSegmentPolicy 的 `dynamic_tail` section，sealed replay 例外委托 ProviderMessageReplayContract。
- task contract intake 已移除 versioned compact task start intent 名称；旧 `task_contract_seed` / layered contract seed 不再迁移成 canonical Work Mode，只作为 validation error / repair diagnostic。
- dynamic context replacement identity 已移除 `_v3` / `.v3` 后缀和 `projector_version` 字段名；投影身份统一为稳定 `projector_id`，provider-visible ledger entry hash salt 也不再携带版本后缀。
- 自有 active runtime authority/protocol/schema identity 已继续去掉 `.v1` / `_v1` 后缀：chat live protocol、assistant stream frame identity、context recovery package、runtime cache manifest、file observation/read evidence/read file window、run monitor、public read-file window projection 和 DeepSeek provider-visible adapter contract 均改为稳定身份。模型事实命名如 `deepseek_v4` 不属于运行契约版本后缀。
- 2026-06-30 继续清理：task/file evidence 合同身份统一为 `contract_id`，不再生成 `contract_version`；assistant stream frame、context recovery package、runtime cache manifest、session projection slice 分别使用 `frame_schema_id`、`package_schema_id`、`manifest_schema_id`、`projection_schema_id`；TurnMemory、provider-visible ledger、physical prefix frame ledger、context commit record 的落盘结构号改为 `record_schema_revision` / `ledger_schema_revision`，避免与上下文段身份混名。
- tool call transport 已删除 provider-native 工具调用失败后自动转 JSON action object 的执行层 fallback；`ToolCallContract` 不再读取 `action_object_tool_fallback_enabled/tool_fallback_enabled`，执行层不再通过错误文本猜测并切换工具 transport。显式 `ordinary_tool_submission=action_object` 仍只能由上游契约决定。
- provider-visible ledger 已删除 `last_provider_success_anchor` / `last_success_anchor_id` legacy alias；当前 provider-visible 游标只由 `active_provider_success_anchor`、`active_success_anchor_id`、`active_terminal_entry_index` 和 `active_terminal_entry_hash` 表达。
- `resume_task_recovery` 已从 turn action request 缺省可见动作集合移除；它只在 task recovery/control 明确 allowed 时出现，普通 TurnMemory recovery 模型可见段继续声明 forbidden action。
- 普通 single-agent compiler 已停止读取和投影 `session_context["recovery_boundary_receipt"]`；continuation recovery receipt 只保留在 task recovery/control 边界内。agent contract feedback 只读取 `next_action_requirements`，旧 `required_action_protocol` 不再作为兼容输入。
- context_capability_policy.py 的 prompt resource 归属已切到显式 metadata、内置 rule kind 精确目录、category/subtype 与 environment_guidance_slot；未知 rule kind 不再靠 `tool/permission/subagent/coding` 字符串形状获得能力组。
- context_capability_policy.py 的 contract slot 归属已切到显式 slot 目录、semantic slot 目录和 registry capability；不再通过 `tool` 子串或 `tool_` kind 前缀进入 `TOOL_CONTEXT`。
- prompt_library.assembly 的 stable prompt gate bypass 不再读取 `system.foundation.*` / `runtime.*` prompt ref 前缀；只接受 `builtin_runtime_prompt=True` 或 `category=system/subtype=foundation/source_type=builtin_system_foundation_prompt`。
- prompt_library.rules 的 foundation coverage 不再读取 `rule_kind.startswith("system.foundation")`；PromptSection 透传资源 `source_type`，coverage 只读显式 category/subtype/source_type。
- harness.runtime.assembly 的 system wiring prompt gate 不再读取 `runtime.*` prompt ref 前缀来跳过 gate；`prompt_resource_gates` 必须记录所有系统组声明的 prompt resource，运行时身份由资源 metadata/category/rule kind 和显式 system group 连接表达。
- context_prefix_identity、provider_visible_context_ledger、serializer、provider_payload 和 context_contract authority projection 已停止把 `content_source/source_kind/context_source_kind` 转译为 prefix origin authority 或 provider-visible item identity；来源标签只保留为审计/描述。
- `authority_class` 已从 active Python 代码退场：prompt composition、prompt accounting、context segment registry、harness compiler/context producers/follow-up specs、memory maintenance specs 和 ContextContract refs 均不再生成、读取、转发或展示该字段。
- 缺少 connection_contract_ref / control_signal / agent_domain 会进入 diagnostics。
- ContextContractNode / context_contract_inspection 已移除 semantic_kind / semantic_layer / semantic_time。
- ContextContractManifest.edges 已扩展为四类标准连接契约，缺少 edge identity/authority/payload/target 会进入 diagnostics。
```

完成标准：

```text
缺少 explicit contract 会报 diagnostic
不会用 kind 字符串猜 agent_domain
```

### Phase 4：清理缓存旧账本和旧健康口径

状态：已完成主链路。`prefix_state.jsonl` 已成为 prefix continuity/reset 权威；`cache_plans.jsonl` 已成为 preflight cache plan 权威；provider result 只通过 `provider_cache_bus.jsonl` 输出当前缓存裁决。

2026-06-30 继续更新：`context_contract_node_ref/context_contract_edge_refs` 已从 `PromptSegmentPlan` 透传到 `ProviderPayloadSegment`、`CachePlanRecord` diagnostics、`PrefixCacheHealth.first_missing_expected_prefix_identity` 和 `ProviderCacheBusRecord`。缓存 under-read 可以回到具体 ContextContract node/edge。

2026-06-30 prefix state memory 身份继续收口：`prefix_state.memory_segment_hash` 不再接受 `authority_class`、`content_source` 或 `authority=memory_system.*` 作为未知段进入 memory hash 的资格。memory identity 只来自显式 memory kind、registry `CONTEXT_MEMORY` capability、`agent_domain=ContextMemoryDomain` + selected memory slot，或 `semantic_commit_class=selected_memory_context`。

涉及文件：

```text
backend/runtime/model_gateway/model_runtime.py
backend/runtime/prompt_accounting/ledger.py
backend/runtime/prompt_accounting/prefix_state.py
backend/runtime/prompt_accounting/prefix_state_diff.py
backend/runtime/prompt_accounting/prefix_state_diff_models.py
backend/bootstrap/app_runtime.py
backend/api/tokens.py
backend/health_system/governance.py
frontend/src/components/chat/ChatPanel.tsx
frontend/src/features/health/healthSelectors.ts
```

动作：

- `model_runtime.py` 不再为新 request 写 `prompt_cache_baselines.jsonl` 和 `prompt_stability.jsonl`。
- `model_runtime.py` 不再构造 baseline helper；`PrefixStateReporter` 直接生成一条 `prefix_state` 单记录，下一轮 previous 只读 `prefix_state`，并尊重 invalidated reset 边界。
- `stability_report.py` / `stability_models.py` 已退出 active code；prefix diff helper 当前命名为 `PrefixStateDiffReporter` / `PrefixStateDiffReport`，避免继续表现为第二状态权威。
- `prefix_state.py` 删除旧 baseline diagnostics fallback；`provider_lane.py` 删除显式 legacy lane alias。
- `provider_lane_from_accounting_context()` 删除 `source/call_kind` 字符串猜测；utility 与 semantic compaction 显式写入 provider lane。
- `ledger.py` 删除旧 baseline/stability record/list/reset 入口；retention/prune 只处理 `prefix_state`。
- `app_runtime.py` 已改读 `build_provider_cache_log_view()`，用 `current_prefix_covered` 判断 warm/cold。
- `api/sessions.py` 和 compact boundary 已改写 `reset_prefix_state()` invalidated 记录。
- health/frontend 展示缓存时：

```text
primary: latest_status / latest_prefix_health / latest_under_read_tokens / current_prefix_covered
secondary: hit_rate / cached_tokens
```

完成标准：

```text
cached_tokens > 0 不能再被当作缓存健康
77.19% 总命中率不能覆盖 provider_under_read
旧 baseline/stability 不再由新请求写入
prefix continuity/reset 只走 prefix_state
```

### Phase 5：TurnMemory 恢复权威清洗

状态：已完成普通 single-agent turn 主链路清洗；task recovery/control 体系保留原动作类型和边界校验。

涉及文件：

```text
backend/harness/entrypoint/runtime_facade.py
backend/harness/runtime/compiler.py
backend/harness/continuation/selector.py
backend/harness/continuation/record.py
backend/runtime/turn_memory/*
```

动作：

- `TurnMemoryRecoveryContext` 继续作为唯一 recoverable active state。
- `runtime_facade.py` 不再设置 `session_context["recoverable_work"]`。
- `request_facts.py` 不再记录 `recoverable_work_candidate`。
- `packet_assembler.py` 不再从旧 continuation record 派生 `resume_task_recovery` 普通 turn 动作面。
- `compiler.py` 不再把 `recoverable_work` 加入 `single_turn_dynamic_refs` 或 volatile runtime payload。
- `compiler.py` 不再把 `recovery_boundary_receipt` 加入普通 turn `single_turn_dynamic_refs` 或模型可见 runtime payload；该 receipt 只服务 task recovery/control。
- `selector.py` / `compiler.py` 不再读取旧 `required_action_protocol`；agent contract feedback 的下一步动作要求统一为 `next_action_requirements`。
- `visible_assistant_prefix` 只保留为 UI replay / read-only diagnostic，不作为恢复 prompt source。
- `continuation_selection` 只报告选择证据，不拥有恢复决策。

完成标准：

```text
模型可见恢复段只来自 turn_memory_recovery
旧 continuation 不能重跑或改写 active turn 意图
```

### Phase 6：protected old context 收口为物理 replay 契约

状态：已完成。旧 `runtime.shared.protected_context` 已删除，byte-preserve 判断统一迁入 `runtime.context_management.provider_message_replay_contract`。合法 replay contract 只剩两类：`physical_prefix_frame_replay` 与 `provider_protocol_replay`。

涉及文件：

```text
backend/runtime/context_management/provider_message_replay_contract.py
backend/runtime/context_management/context_pipeline.py
backend/runtime/context_management/physical_context_assembler.py
backend/runtime/context_management/physical_context_plan.py
backend/runtime/context_management/followup_context_rebase.py
backend/harness/runtime/compiler.py
backend/harness/loop/single_agent_turn.py
backend/prompt_composition/materializer.py
```

动作：

- 将 `protected_old_context_spec` 删除，替换为 `provider_message_byte_preservation_required()`。
- `context_pipeline.py` 的 capability stage 不再写 `bypassed_for_protected_old_context`，改写 `preserved_by_provider_message_replay_contract`。
- `physical_context_assembler.py` 的输出字段从 `old_context_specs` 改为 `frame_replay_specs`，诊断字段改为 `provider_message_replay_source` / `physical_prefix_frame_replay_spec_count`。
- `followup_context_rebase.py` 与 `single_agent_turn.py` 将 `current_turn_exact_old_context` 改为 `provider_protocol_replay` / `provider_protocol_prefix_replay`。
- `compiler.py` 与 `prompt_composition.materializer` 只通过 provider message replay contract 决定是否保留原始 provider message bytes。

完成标准：

```text
旧上下文原样 replay 被解释为物理契约
不是散落在 capability/sanitizer 里的兼容 bypass
provider protocol replay 被解释为同 turn provider message byte-preservation，不再叫 old context
```

### Phase 7：删除目标架构中的 semantic 语言中心

涉及文件：

```text
backend/harness/runtime/context_contract/*
frontend/src/lib/api/types.ts
frontend/src/app/agent-network/page.tsx
backend/runtime/context_management/design_docs/semantic_space/*
```

动作：

- 新 graph 和 inspector 使用 `agent_domain/control_signal/time_scope/physical_lane`。
- active ContextContract 和 inspector 不再输出 `semantic_kind/semantic_layer/semantic_time`。
- 剩余 `semantic_*` 命名必须绑定具体领域边界，不能进入 runtime control contract 主链路。
- 旧 `semantic_space` 文档保留为历史研究，不继续作为执行计划名称中心。
- 2026-06-30 继续清理：`session_runtime_timeline` 的 live projection 裁剪不再使用泛化 `semantic_roots` 命名，改为 `projection_roots`；未使用的 tool lifecycle closure 旧选择 helper 已删除。live projection 上限由 `_bounded_projection_frames()` 单点执行，按最近 projection root + 工具 lifecycle closure 的预算包选择，不能再因全量根帧预选绕过 `max_projection_frames_per_attachment`。
- 2026-06-30 继续清理：runtime interruption 诊断字段从 `semantic_terminal=false` 改为 `agent_decision_terminal=false`，表达“不是 agent 决策终局，而是运行时可恢复中断”。`semantic_actions` 改为 `allowed_action_types`，`semantic_decision_owner` 改为 `decision_owner`。recoverable orphaned run 不再由 `stream_replay` 自动补 public `turn_completed` terminal reconciliation。
- 2026-06-30 继续清理：`single_agent_turn.py` 的 runtime follow-up 段元数据从 `runtime_control_semantic_role` 改为 `runtime_control_role`；`prompt_accounting.serializer` 不再把无 active producer 的 `semantic_role` 写入 prompt accounting metadata。task graph 的 `semantic_role` 属于图系统外围模型，不纳入本轮单 agent runtime spine 清洗。
- 2026-06-30 继续清理：`semantic_memory_visible` / `semantic_memory_commit_policy` 退出 active runtime metadata。动态 runtime tail 和 replay-only candidate 使用 `context_memory_visible=false` / `context_memory_commit_policy=never_commit`，physical frame replay 使用已有 `memory_commit_policy` 表达 replay-only 记忆提交策略。

完成标准：

```text
目标架构文档和新 API 不再以 semantic_* 作为主命名体系
```

## 7. 删除候选清单

| 候选 | 删除/降级原因 | 替代者 | 删除条件 |
| --- | --- | --- | --- |
| 前端 `CORE_NODES` / `CORE_EDGES` 作为 core graph | 无后端证据，假权威 | `GET /api/agent-control-network` | 已删除前端 core authority，保留本文为旧问题记录 |
| `authority_rules.py` 主分类路径 | 字符串启发式决定控制域 | ContextContract 标准控制字段 | Phase 3 主链路完成 |
| 新 request 写 `prompt_cache_baselines.jsonl` | legacy prefix state 双写 | provider_cache_bus + prefix_state/manifest | Phase 4 迁移完成 |
| `cache_baseline.py` active helper | prefix continuity/generation 决策仍绕旧层 | PrefixStateReporter | 已删除 active code |
| 新 request 写 `prompt_stability.jsonl` | 与 ProviderCacheBus 重叠，且同 request preflight/result 双写 | provider_cache_bus + manifest diff | Phase 4 迁移完成 |
| `cached_tokens > 0 -> warm` | 总命中不能证明前缀命中 | current_prefix_covered / under-read / latest_prefix_health.verdict | 已由 `provider_cache_prefix_health_authority_cleanup_20260630.md` 收口 |
| `recoverable_work` 作为 active recovery prompt | 与 TurnMemory 恢复权威重复 | TurnMemoryRecoveryContext | Phase 5 完成 |
| `visible_assistant_prefix` 作为恢复权威 | UI visible stream 不是 hot ledger | TurnMemory draft/checkpoint refs | Phase 5 完成 |
| legacy protected-context bypass 文案/散落判断 | 正确需求，但表达为旁路 | ProviderMessageReplayContract | Phase 6 完成 |
| `authority_class` active 字段 | 旧类别标签会绕过或污染四段物理段、ContextContract capability、prompt accounting 和诊断展示 | physical lane + context capability + semantic slot + connection contract + explicit origin | 已从 active Python 代码移除 |
| `content_source` 决定 fragments 使用 spec 还是 fallback model message | 来源描述字段变成 byte-preserve 控制入口 | ProviderMessageReplayContract | 已改为统一 replay contract 判定 |
| dynamic context metadata validation 的 `kind.startswith("dynamic")` | kind 名字会伪装成动态段或漏掉显式 dynamic_tail | cache_role=volatile + ContextSegmentPolicy dynamic_tail + ProviderMessageReplayContract | 已从 `harness.runtime.compiler` 移除 |
| task contract legacy seed auto-migration | `task_contract_seed` / `goal_contract` / `plan_contract` 会让系统替模型重写任务合同 | canonical `task_run_contract_seed` 或 `compact_task_start_intent`，旧字段只报错 | 已从 `model_action_protocol`、`task_lifecycle`、`task_run_contract_manifest` 主入口移除 |
| prompt rule kind / contract slot 字符串启发式能力归属 | `tool/permission/subagent/coding` 或 `tool_` 这类文本形状会伪装成能力授权 | explicit metadata + exact rule/slot catalog + registry capability | 已从 `context_capability_policy.py` active 决策移除 |
| prompt ref 前缀 stable gate bypass | `system.foundation.*` / `runtime.*` 这类 id 形状会绕过 capability gate | 资源显式 metadata：`builtin_runtime_prompt` / `builtin_system_foundation_prompt` | 已从 `prompt_library.assembly` active gate 移除 |
| prompt rule diagnostics 的 `system.foundation*` 前缀 coverage | 诊断覆盖项仍把 rule_kind 形状当 foundation 身份 | PromptSection category/subtype/source_type | 已从 `prompt_library.rules` coverage 移除 |
| system wiring prompt gate 的 `runtime.*` 前缀 diagnostic-only bypass | 运行时 ref 名字会让系统组 prompt resource 消失在 gate 记录中 | 显式 system group prompt_resources + prompt resource metadata/category/rule kind | 已从 `harness.runtime.assembly` active gate 移除 |
| `content_source/source_kind/context_source_kind` 参与 prefix/provider-visible identity | 来源标签变化会让同一上下文段变成新 prefix identity 或新 provider-visible item | explicit origin authority + prefix identity + source_ref/kind fallback | 已从 prefix identity、provider payload、serializer、provider-visible ledger 和 ContextContract authority projection 移除 |
| provider-native tool invocation 自动 fallback 到 JSON action | 执行层根据 provider 错误文本重新决定工具 transport，形成第二条工具调用路径 | `ToolCallContract.ordinary_tool_submission` 一次性决定 transport，失败进入模型错误/恢复路径 | 已从 `single_agent_turn` 和 `ToolCallContract` active path 移除 |
| `last_provider_success_anchor` legacy alias | 与 `active_provider_success_anchor` 表达同一 provider-visible 游标，形成双字段权威 | `active_provider_success_anchor` / `active_success_anchor_id` | 已从 provider-visible ledger 读取和写入移除 |
| `session_runtime_timeline` 泛化 semantic root 命名和未用 closure helper | live projection 裁剪应表达投影根帧预算，不应把 semantic 作为 runtime control 主语言；未用 helper 会留下第二选择入口 | `projection_roots` + `_bounded_projection_frames()` 单点预算裁剪 | 已从 active code 改名并删除未用 helper |
| `semantic_terminal` / `semantic_actions` / `semantic_decision_owner` runtime 控制字段 | 泛化 semantic 语言进入恢复裁决、动作面和 runtime interruption signal，容易把 agent 决策权与系统传输终端混名 | `agent_decision_terminal` / `allowed_action_types` / `decision_owner` | 已从 active code 和当前测试断言移除；旧 hot recovery 文档同步为新字段 |
| `runtime_control_semantic_role` follow-up 元数据 | runtime 控制段角色不应表达为 semantic role | `runtime_control_role` | 已从 `single_agent_turn.py` active path 移除 |
| `semantic_memory_visible` / `semantic_memory_commit_policy` | 记忆可见性/提交策略不是 semantic identity | `context_memory_visible` / `context_memory_commit_policy` / `memory_commit_policy` | 已从 active code 移除 |

## 8. 不变量

1. 四段物理模型是唯一上下文物理权威。
2. `ProviderPayloadManifest` 是 provider request/hidden transport 权威。
3. `ProviderCacheBus` 是前端缓存日志和缓存健康展示权威。
4. `prefix_cache_health` 是 expected prefix 命中裁决算法。
5. `TurnMemory` 是 turn 间热账本，不写 sealed history。
6. `ProviderVisibleLedger` / `PhysicalPrefixFrameLedger` 是 Past replay 权威。
7. 前端不重新解释 runtime authority。
8. 旧逻辑只能作为有期限 diagnostics，不能保留为 active fallback。
9. 缺少控制契约时显式报错或诊断，不猜测。
10. 不新增测试文件；用静态审查、编译检查、固定端口真实运行验收。
11. 控制网络主链路不使用 `schema_version`、`.vN`、`_vN`、`new_*` 或 `native_*` 作为自有主链路标识；读模型身份使用稳定 `schema` / `*_id` / `*_contract`。
    - 真正的落盘结构修订只能命名为 `*_schema_revision`，不能复用 `schema_version` 作为上下文身份。
    - graph/project/personality 等外围数据模型的历史 `schema_version` 不在本轮单 agent runtime spine 清理范围，后续如进入主链路再单独治理。
12. `authority_class` 不允许重新进入 active Python 代码；历史文档可记录旧问题，但运行链路不得生成、读取、转发或展示该字段。
13. `content_source` / `source_kind` 只能描述来源和统计，不能决定 replay、byte-preserve、物理段或缓存命中资格。
14. `prompt_ref`、`rule_kind`、`context_contract_slot` 和 `kind` 的字符串形状不能绕过 ContextCapability、prompt gate 或 system wiring gate；能力只能来自显式 metadata、精确目录、registry capability、资源类别契约和系统组显式连接。
15. `content_source/source_kind/context_source_kind` 不能参与 prefix origin authority、logical segment ref、provider-visible ledger item key 或 ContextContract authority projection。

## 9. 验证方案

静态审查：

```powershell
rg -n "CORE_NODES|CORE_EDGES" frontend/src/app/agent-network/page.tsx
rg -n "classify_context_spec|authority_rules" backend/harness/runtime/context_contract
rg -n "record_prompt_cache_baseline|record_prompt_stability|PROMPT_CACHE_BASELINES_FILE|PROMPT_STABILITY_FILE" backend/runtime backend/api backend/health_system
rg -n "cached_tokens > 0|cache_temperature|provider_under_read|current_prefix_covered" backend frontend/src
rg -n "recoverable_work|interrupted_turn_work|visible_assistant_prefix|turn_memory_recovery" backend/harness backend/runtime
```

编译检查：

```powershell
python -m py_compile backend/harness/runtime/context_contract/inspection_payload.py backend/harness/runtime/context_contract/diagnostics.py backend/api/agent_control_network.py backend/app.py
python -m py_compile backend/harness/runtime/context_contract/nodes.py backend/harness/runtime/context_contract/manifest.py backend/runtime/model_gateway/model_runtime.py backend/runtime/prompt_accounting/ledger.py backend/runtime/prompt_accounting/provider_cache_bus.py backend/runtime/prompt_accounting/prefix_cache_health.py backend/harness/runtime/compiler.py backend/harness/entrypoint/runtime_facade.py
```

前端检查：

```powershell
npx tsc --noEmit
npm run lint
```

固定端口真实运行：

```text
backend:  http://127.0.0.1:8003
frontend: http://127.0.0.1:3000
```

API/页面验收：

```powershell
Invoke-WebRequest -UseBasicParsing http://127.0.0.1:8003/api/agent-control-network
Invoke-WebRequest -UseBasicParsing http://127.0.0.1:8003/api/agent-control-network/session/<session_id>
Invoke-WebRequest -UseBasicParsing http://127.0.0.1:3000/agent-network
```

真实缓存验收：

```text
latest_status != provider_under_read
latest_under_read_tokens == 0
current_prefix_covered == true
first_missing_expected_prefix_identity == {}
```

如果 provider 外部缓存过期或 provider-side eviction 导致 miss，应报告为 provider 外部状态，不能用本地总 hit rate 掩盖。

## 10. 推荐实施顺序

推荐连续实施：

```text
Phase 1 harness runtime topology projection
-> Phase 2 前端切后端权威
-> Phase 3 ContextContract explicit contract
-> Phase 4 cache legacy ledger cleanup
-> Phase 5 TurnMemory recovery cleanup
-> Phase 6 protected replay contract cleanup
-> Phase 7 naming/presentation cleanup
```

原因：

- 先建立只读网络，才能看到真实连接。
- 再清理前端静态假权威。
- 然后替换 ContextContract 字符串分类。
- 最后删除旧缓存账本、旧恢复分支和旧命名中心。

## 11. 确认状态

### 2026-06-30 执行记录：task run signal 收口

本轮完成 `task_contract_seed` 下游旧链路清理：

- 新增 `task_system.contracts.task_run_signal` 作为只读投影入口，消费 `task_run_contract` / `task_run_contract_seed` / `agent_turn_action_request.task_run_contract_seed`，不再把旧 `task_contract_seed` 当 active 输入。
- `task_system.tasks.definitions`、`task_system.contracts.task_requirement_contracts`、`task_system.contracts.execution_obligation`、`task_system.services.assembly_support`、`task_system.services.assembly_builder`、`task_system.planning.execution_shape_resolver` 已接入 `task_run_contract_signal`。
- `task_shape` 不再被自动改写成 `task_goal_type`；资源形态和业务目标类型保持分离，避免系统替 agent 重写语义。
- 前端 `internalControlText` 已识别 `task_run_contract_seed`、`task_recovery_resume`、`pause_request` 等新控制字段；旧 `task_contract_seed` 仅保留为泄露检测。
- 既有 task contract/model response 断言已从旧 seed 改为 TaskRunContract / compact TaskStartIntent 语义。
- `task_system.contracts.TaskContract` 和 `TaskContractIssuer` 产物已移除 active `schema_version` / `.v1` request plan 字段；身份保留在 `kind`、`contract_kind`、`authority` 和 refs 上。
- `harness.loop.task_lifecycle` 已停止在 `runtime_contract` 里生成派生 `task_contract` 投影，`runtime_contract` 只保留 `task_run_contract` 作为任务运行合同主权威。
- `harness.runtime.dynamic_context` 输入、section report 和 active lease/turn attention 投影已改为 `task_run_contract` 命名；active lease 不再读取 `runtime_contract.task_contract` 派生块。

保留边界：

- `backend/harness/loop/model_action_protocol.py` 中 `task_contract_seed` 只作为非法字段报错：`legacy_task_contract_seed_field_not_allowed:task_contract_seed`。
- `backend/runtime/model_gateway/model_response_protocol.py` 可继续识别旧字段形状为 action-like 解析线索，但不得把旧字段迁移为合法合同。
- 前端可以检测并隐藏旧字段泄露，但不能把旧字段作为正常 UI 协议。

本轮验证：

```powershell
python -m py_compile backend/task_system/contracts/task_run_signal.py backend/task_system/tasks/definitions.py backend/task_system/contracts/task_requirement_contracts.py backend/task_system/contracts/execution_obligation.py backend/task_system/services/assembly_support.py backend/task_system/services/assembly_builder.py backend/task_system/planning/execution_shape_resolver.py backend/harness/loop/model_action_protocol.py backend/tests/model_response_protocol_regression.py backend/tests/task_run_contract_manifest_regression.py
python -m py_compile backend/task_system/contracts/contracts.py backend/task_system/assembly/contract_issuer.py backend/tests/task_contract_issuer_regression.py
python -m py_compile backend/harness/runtime/dynamic_context/models.py backend/harness/runtime/dynamic_context/manager.py backend/harness/runtime/dynamic_context/active_execution_lease.py backend/harness/runtime/dynamic_context/turn_state_attention_context.py backend/harness/runtime/compiler.py backend/harness/loop/task_lifecycle.py
rg -n "task_contract_seed|canonical_task_contract_seed|_normalize_task_contract_seed" backend/task_system backend/tests/model_response_protocol_regression.py backend/tests/task_run_contract_manifest_regression.py backend/harness/loop/model_action_protocol.py frontend/src/lib/internalControlText.ts --glob "!**/*.md"
rg -n "compact_task_start_intent_v3|_v3\b|\bv3\b|schema_version" backend/harness backend/runtime backend/task_system frontend/src --glob "!backend/runtime/context_management/design_docs/**" --glob "!**/*.md"
rg -n "derived_task_contract_projection|get\(\"task_contract\"\)|\[\"task_contract\"\]" backend/harness backend/runtime backend/task_system --glob "!backend/runtime/context_management/design_docs/**" --glob "!**/*.md"
```

扫描结果：旧 task seed 只剩合法非法字段/泄露检测语境；`derived_task_contract_projection` 和 `runtime_contract.task_contract` 读取已清空；`schema_version` 剩余项只在 graph/project/library 外围数据模型和前端 API 类型，不在本轮单 agent runtime spine 主链路。

### 2026-06-30 执行记录：显式任务入口与前缀身份收口

本轮继续清理 `task_contract` 旧命名对单 agent runtime spine 的污染：

- CLI `task-run start --contract-file` 只生成 `runtime_contract.task_run_contract` / `task_run_contract_seed` / `engagement_contract`，不再把普通 JSON 包成 `task_contract`。
- `runtime_contract.task_run_contract` 只有在 `system_issued_contract=true` 或合同自身 `system_issued=true` 时才会走 `explicit_contract_task`；普通 turn 中携带同名片段不会绕过 agent 当前 turn。
- TaskSystem assembly bundle 出口从 `"task_contract"` 改为 `"task_system_contract"`，表达这是 TaskSystem 自己的装配合同，不是 Harness 的 `TaskRunContract`。
- Runtime admission 读取 `task_system_contract` 作为 TaskSystem 装配输入；不再读取旧 `"task_contract"` bundle 键。
- 物理段 identity 统一为 `task_run_contract_stable`，删除 registry 中旧 `task_contract_stable` 声明；prompt slot layer 从 `task_contract_context` 改为 `task_run_contract_context`。
- Manifest 模块、类、packet 字段、prompt manifest key 统一为 `task_run_contract_manifest` / `TaskRunContractManifest`，不再保留 `task_contract_manifest` 可观测字段。
- 模型可见 runtime payload 标题从 `Task execution task contract` 改为 `Task execution task run contract`，物理段标题、payload key 和 segment kind 三者一致。
- `execution_shape_resolver` 的 `resolution_source` / reason 从 `task_contract` 改为 `task_run_contract_signal`，诊断来源与真实投影入口一致。
- Context capability policy 对 task/graph prompt 的默认 capability slot 从 `task_contract` 改为 `task_run_contract`。

保留边界：

- `task_contract_seed` 只允许作为非法字段检测、action-like 解析线索和前端控制文本泄露检测存在。
- `TaskRunContractManifest` 输出的模型可见 payload 与物理段 identity 是 `task_run_contract` / `task_run_contract_stable`。
- `TaskRun.task_run_contract_ref` 已成为 TaskRun 持久模型/API 字段；它只指向同一类 `task_run_contract` runtime object，不再保留 `task_contract_ref` 可观测字段。
- `TaskRunContract` 只有一个契约模型。模型发起与用户直接发起只通过 `contract_source` / `origin` 记录来源，不允许拆成 model contract / user contract 两套契约类型或两条生命周期链路。

本轮验证：

```powershell
rg -n '"task_contract"|''task_contract''|task_contract_stable|task_contract_context|task_contract_manifest|resolution_source="task_contract"|task_contract_source:|default_task_contract|task_contract_seed|canonical_task_contract_seed|_normalize_task_contract_seed|compact_task_start_intent_v3|_v3\b' backend/cli backend/harness backend/runtime backend/task_system backend/permissions backend/prompt_composition frontend/src backend/tests --glob '!backend/runtime/context_management/design_docs/**' --glob '!**/*.md'
python -m py_compile backend/cli/main.py backend/task_system/services/assembly_builder.py backend/permissions/runtime_policy_builder.py backend/runtime/context_management/context_segment_registry.py backend/runtime/context_management/context_capability_policy.py backend/prompt_composition/slot_policy.py backend/prompt_composition/manifest.py backend/task_system/planning/execution_shape_resolver.py backend/harness/runtime/task_run_contract_manifest.py backend/harness/runtime/invocation_packet.py backend/harness/runtime/compiler.py backend/tests/harness_task_lifecycle_control_regression.py backend/tests/plan_mode_protocol_regression.py backend/tests/task_run_contract_manifest_regression.py backend/tests/prompt_assembly_authority_regression.py backend/tests/tool_catalog_manifest_regression.py backend/scripts/diagnose_real_writing_prompt_cache.py
```

扫描结果：旧 `"task_contract"`、`task_contract_stable`、`task_contract_context`、`task_contract_manifest`、`resolution_source="task_contract"` 已从本轮 active 扫描范围清空；剩余 `task_contract_seed` 均为非法字段/泄露检测语境。

### 2026-06-30 执行记录：TaskRunContract 来源收口

本轮根据“契约本体一致，来源只做元数据区分”的原则继续收口：

- `runtime.shared.models.TaskRun`、state index、monitor projection、continuation、retention、health projection、frontend API type 已统一为 `task_run_contract_ref`，不再暴露 `task_contract_ref` active 字段。
- 模型发起任务和用户直接发起任务都生成同一个 `TaskRunContract`，并进入同一个 `start_task_lifecycle` 创建同一类 `TaskRun` / `task_run_contract` runtime object。
- `contract_source` 只作为来源总类：
  - `model_action_request`：模型在当前 turn 中发起 `request_task_run`。
  - `user_direct_request`：用户/系统边界已经给出明确任务合同，Harness 直接接入同一 TaskRunContract 链路。
- `origin` / `origin_kind` 只作为更细粒度入口证据，例如 `single_agent_turn_json_action`、`single_agent_turn_native_tool_call`、`user_direct_request`。它不得升级成契约类型，也不得创建第二套生命周期链路。
- 诊断脚本 `diagnose_real_writing_prompt_cache.py` 已同步使用 `task_run_contract_ref`，避免缓存排查继续输出旧字段。

本轮验证：

```powershell
rg -n 'task_contract_ref' backend frontend/src --glob '!backend/runtime/context_management/design_docs/**' --glob '!**/*.md'
rg -n -e 'task_contract_manifest' -e 'TaskContractManifest' -e 'task_contract_stable' -e 'task_contract_context' -e 'Task execution task contract' -e 'resolution_source="task_contract"' -e 'task_contract_seed' -e 'canonical_task_contract_seed' -e '_normalize_task_contract_seed' backend\harness backend\runtime backend\task_system backend\permissions backend\prompt_composition frontend\src backend\tests --glob '!backend/runtime/context_management/design_docs/**' --glob '!**/*.md'
rg -n 'contract_source="model_request"|contract_source.: .model_request.|model_request' backend\harness backend\tests --glob '!**/*.md'
python -m py_compile backend/runtime/shared/models.py backend/runtime/memory/state_index.py backend/harness/loop/task_lifecycle.py backend/harness/entrypoint/runtime_facade.py backend/harness/continuation/record.py backend/harness/continuation/selector.py backend/harness/runtime/task_run_retention.py backend/harness/runtime/task_record_lifecycle.py backend/runtime/shared/artifact_refs.py backend/harness/runtime/run_monitor/projector.py backend/harness/loop/task_executor.py backend/harness/agent_control/controller.py backend/harness/runtime/invocation_packet.py backend/harness/runtime/prompt_segment_plan.py backend/health_system/governance.py backend/health_system/execution_planner.py backend/task_system/tasks/run_models.py backend/graph_system/runtime.py backend/scripts/diagnose_real_writing_prompt_cache.py
```

扫描结果：active 代码中 `task_contract_ref` 已清空；旧 manifest/segment 名称未命中；旧 `task_contract_seed` 只剩非法字段检测、泄露检测和 action-like 解析线索；旧 `model_request` 来源名未命中。

本轮保留的外围边界：

- `graph_node_work_order` 仍存在于 graph runtime / graph prompt projection。用户已明确当前不处理图结构，不能把 graph 来源混入单 agent 两入口模型。
- `subagent_control` 已在下一片清理中接入同一 `task_run_contract` runtime object 存储；它仍是外围来源，但不再是 diagnostics-only 第三条隐式契约链路。

### 2026-06-30 执行记录：Subagent 外围契约接入同一 TaskRunContract 存储

本轮清理 `subagent_control` 创建子任务时的隐式合同路径：

- `SubagentControl._append_child_task_run` 现在先生成 `TaskRunContract`，写入 `runtime_objects.put_object("task_run_contract", ...)`，再把返回的 ref 写入 `TaskRun.task_run_contract_ref`。
- 子任务 `TaskLifecycleRecord.contract_ref` 指向同一个 `task_run_contract_ref`，避免 lifecycle 和 task run 分别指向不同合同来源。
- `subagent_control` 保留为 `contract_source` / `origin.origin_kind` 来源元数据，不再使用 `task_system.task_contract` authority，也不再用空 `task_run_contract_ref` 触发 executor 的 diagnostics fallback。
- `runtime_contract_from_task_run_contract` 提升为 `harness.loop.task_lifecycle` 的显式构造函数，由普通 task lifecycle 和 subagent 子任务共同复用，避免新建第二套 runtime contract 投影逻辑；subagent controller 使用局部导入，避免 `state_index -> agent_control -> task_lifecycle` 循环依赖。
- `task_executor._load_contract` 已停止从 `diagnostics["contract"]` 回退执行；执行器只信 `TaskRun.task_run_contract_ref` 指向的 runtime object。缺失时失败为 `task_run_contract_missing`。
- `task_executor._task_runtime_permission_mode` 已停止从 `diagnostics["contract"]` 推断权限模式；初始 assemble 只读取已经由 `task_run_contract_ref` 加载出的 `TaskRunContract`。
- `active_execution_lease` 已停止从 `diagnostics["contract"]` / `diagnostics["task_run_contract"]` 回退生成模型可见执行租约；动态上下文只接收 compiler 传入的显式 `task_run_contract`。

本轮验证：

```powershell
python -m py_compile backend/harness/agent_control/controller.py backend/harness/loop/task_lifecycle.py backend/runtime/tool_runtime/tool_control_plane.py
$env:PYTHONPATH='backend'; python -c "from harness.agent_control.controller import SubagentControl; from harness.loop.task_lifecycle import runtime_contract_from_task_run_contract; print(SubagentControl.__name__, callable(runtime_contract_from_task_run_contract))"
python -m py_compile backend/harness/loop/task_executor.py backend/harness/agent_control/controller.py backend/harness/loop/task_lifecycle.py
python -m py_compile backend/harness/runtime/dynamic_context/active_execution_lease.py backend/harness/runtime/dynamic_context/manager.py backend/harness/loop/task_executor.py
$env:PYTHONPATH='backend'; python -c "from harness.loop.task_executor import execute_task_run; from harness.loop.task_lifecycle import runtime_contract_from_task_run_contract; print(callable(execute_task_run), callable(runtime_contract_from_task_run_contract))"
$env:PYTHONPATH='backend'; python -c "from types import SimpleNamespace; from runtime.shared.models import AgentRun; from harness.agent_control.controller import _subagent_task_run_contract; child=AgentRun(agent_run_id='agrun:child', task_run_id='taskrun:child', agent_id='agent:verifier', agent_profile_id='completion_verifier_agent', parent_agent_run_ref='agrun:parent'); parent=SimpleNamespace(task_run_id='taskrun:parent'); contract=_subagent_task_run_contract(parent_task_run=parent, child_task_run_id='taskrun:child', child_agent_run=child, runtime_assembly={'task_environment': {'environment_id': 'env:test'}}, runtime_profile={}, goal='verify output', instructions='', context_refs=['obs:1'], expected_outputs=['verdict']); payload=contract.to_dict(); print(payload['authority']); print(payload['contract_source']); print(payload['origin']['origin_kind']); print(payload['work_modes'][0]['mode_kind'])"
rg -n 'diagnostics\.get\("contract"\)|diagnostics\.get\("task_run_contract"\)|task_contract_missing|task_contract_ref|task_run_contract_ref=""|task_run_contract_ref=\"\"|task_system.task_contract|_runtime_contract_from_task_run_contract' backend\harness backend\runtime frontend\src --glob '!backend/runtime/context_management/design_docs/**' --glob '!**/*.md'
rg -n 'task_run_contract_ref=""|task_run_contract_ref=\"\"|task_contract_ref|task_contract_missing' backend --glob '!backend/runtime/context_management/design_docs/**' --glob '!**/*.md'
```

扫描结果：执行/动态上下文 active 范围内旧私有函数名、旧缺失错误名、空 `task_run_contract_ref`、`task_system.task_contract`、`task_contract_ref` 均未命中；`diagnostics["contract"]` 仅剩 run monitor 展示标题兜底。全 backend 唯一空 `task_run_contract_ref` 仍是 `backend/graph_system/runtime.py` 的 graph root TaskRun，属于本轮明确不处理的 graph 结构。

### 2026-06-30 执行记录：单 Agent TaskRunContract 尾部收口

本轮完成计划尾部清理，目标是让单 agent runtime spine 的合同身份、展示、修订和 prompt capability 前缀都落在 `TaskRunContract` 同一条链上：

- `RunMonitorProjector._display_title` 已停止读取 `diagnostics["contract"]` 展示标题；monitor 标题现在只从 TaskRun 公开诊断字段和 `TaskRun.task_run_contract_ref` 指向的 runtime object 读取。
- 用户补充要求产生的合同修订账目从 `task_contract_revision` 收口为 `task_run_contract_revision`：
  - 模块改为 `harness.loop.task_run_contract_revision`。
  - 类改为 `TaskRunContractRevision`。
  - runtime object kind 改为 `task_run_contract_revision`。
  - 事件类型改为 `task_run_contract_revision_recorded` / `task_run_contract_revision_decided`。
  - authority 改为 `harness.loop.task_run_contract_revision.*`。
  - executor 不再读取旧 `diagnostics.task_contract_revision_decisions`，只读取当前 `diagnostics.contract_revision_decisions`。
- 用户显式任务入口信号从 `explicit_task_contract` 改为 `explicit_task_run_contract`，避免把用户直接发起和模型发起误表达成两类合同；两者仍进入同一 TaskRunContract 生命周期，只由 `contract_source` / `origin` 记录来源。
- prompt capability group 从 `task_contracts` / `task_contract_intake` 改为 `task_run_contracts` / `task_run_contract_intake`，模型可见 system group 配置从 `accept_task_contract` 改为 `accept_task_run_contract`。
- `task_contract_invalid` 错误码改为 `task_run_contract_invalid`；artifact scope helper 从 `canonicalize_task_contract_artifacts` 改为 `canonicalize_task_run_contract_artifacts`。
- `harness.task_contract_normalization` 改为 `harness.task_run_contract_normalization`；`task_lifecycle` 内部 `_task_contract_layers` 改为 `_task_run_contract_layers`。
- 未再生产的旧 `task_contract_built` 事件从 runtime event type 和前端 UI 映射中移除。

本轮保留边界：

- `backend/task_system/contracts/contracts.py` 的 `TaskContract` 仍属于 TaskSystem 内部装配域；出口已经是 `task_system_contract`，不再作为 Harness TaskRunContract 主权威出现。
- `task_contract_seed` 只保留在非法字段检测、前端泄露检测和 model response action-like 识别语境中，不能作为合法合同输入。
- `backend/graph_system/runtime.py` 的 graph root 空 `task_run_contract_ref` 仍属 graph 范围，用户已明确当前不处理图结构。

本轮验证：

```powershell
python -m py_compile backend/harness/runtime/run_monitor/projector.py
$env:PYTHONPATH='backend'; python -c "from harness.runtime.run_monitor.projector import RunMonitorProjector; print(RunMonitorProjector.__name__)"
python -m py_compile backend/harness/loop/task_run_contract_revision.py backend/harness/loop/task_executor.py backend/runtime/shared/events.py backend/harness/runtime/run_monitor/projector.py
$env:PYTHONPATH='backend'; python -c "from harness.loop.task_run_contract_revision import TaskRunContractRevision, list_active_task_run_contract_revisions; from harness.loop.task_executor import execute_task_run; print(TaskRunContractRevision.__name__, callable(list_active_task_run_contract_revisions), callable(execute_task_run))"
python -m py_compile backend/runtime/request_signals/request_signals.py backend/runtime/request_signals/frame_access.py backend/task_system/tasks/definitions.py backend/task_system/services/bindings.py backend/scripts/diagnose_real_writing_prompt_cache.py backend/runtime/context_management/context_segment_registry.py backend/runtime/context_management/context_capability_policy.py backend/runtime/prompt_accounting/compression_budget.py backend/harness/runtime/context_contract/authority_rules.py backend/harness/runtime/assembly.py backend/harness/runtime/artifact_scope.py backend/harness/runtime/sandbox_execution_scope.py backend/harness/loop/task_executor.py backend/harness/runtime/projection/projector.py backend/harness/loop/task_lifecycle.py backend/runtime/shared/events.py
$env:PYTHONPATH='backend'; python -c "from runtime.context_management.context_segment_registry import TASK_RUN_CONTRACTS, context_segment_kind_capability; from harness.runtime.assembly import assemble_runtime; from harness.loop.task_executor import execute_task_run; print(TASK_RUN_CONTRACTS, context_segment_kind_capability('task_run_contract_stable'), callable(assemble_runtime), callable(execute_task_run))"
python -m py_compile backend/harness/task_run_contract_normalization.py backend/harness/runtime/task_run_contract_manifest.py backend/harness/loop/task_lifecycle.py backend/harness/entrypoint/runtime_facade.py backend/harness/loop/task_executor.py
$env:PYTHONPATH='backend'; python -c "from harness.task_run_contract_normalization import contract_string_tuple; from harness.loop.task_lifecycle import TaskRunContract; from harness.entrypoint.runtime_facade import HarnessRuntimeFacade; print(contract_string_tuple('a;b'), TaskRunContract.__name__, HarnessRuntimeFacade.__name__)"
rg -n 'explicit_task_contract|task_contract_tokens|task_contract_intake|task_contracts|accept_task_contract|TASK_CONTRACTS|task_contract_invalid|task_contract_built|canonicalize_task_contract_artifacts|task_contract_revision|TaskContractRevision' backend/harness backend/runtime backend/task_system backend/scripts frontend/src --glob '!backend/runtime/context_management/design_docs/**' --glob '!**/*.md'
rg -n 'task_contract_ref' backend/harness backend/runtime backend/scripts frontend/src --glob '!backend/runtime/context_management/design_docs/**' --glob '!**/*.md'
rg -n 'diagnostics.get("contract")' backend/harness backend/runtime backend/scripts frontend/src --glob '!backend/runtime/context_management/design_docs/**' --glob '!**/*.md'
```

扫描结果：单 agent runtime spine 中旧 `diagnostics["contract"]` 展示兜底、旧 `task_contract_revision`、旧 `explicit_task_contract`、旧 `task_contract_intake`、旧 `task_contracts` capability group、旧 `task_contract_invalid` 和旧 artifact helper 均已清空。宽扫描剩余 `task_contract` 只位于 TaskSystem 内部装配域、旧字段非法/泄露检测，以及 graph/任务系统前端配置域，不作为 Harness TaskRunContract 主权威链路。

固定端口真实验收：

```powershell
npx tsc --noEmit
Get-NetTCPConnection -LocalPort 3000 -State Listen
Get-NetTCPConnection -LocalPort 8003 -State Listen
Stop-Process -Id <old_backend_project_pid>
Start-Process -FilePath 'C:/Users/admin/.conda/envs/agent/python.exe' -ArgumentList @('run_uvicorn.py','--host','127.0.0.1','--port','8003') -WorkingDirectory 'D:/AI应用/langchain-agent/backend' -WindowStyle Hidden -PassThru
Invoke-WebRequest -UseBasicParsing http://127.0.0.1:8003/api/agent-control-network
Invoke-WebRequest -UseBasicParsing 'http://127.0.0.1:8003/api/harness/run-monitor?limit=5'
Invoke-WebRequest -UseBasicParsing 'http://127.0.0.1:8003/api/harness/run-monitor/management?limit=5'
Invoke-WebRequest -UseBasicParsing http://127.0.0.1:3000/agent-network
$env:PYTHONPATH='backend'; python -c "from types import SimpleNamespace; from harness.runtime.run_monitor.projector import RunMonitorProjector; store=SimpleNamespace(get_object=lambda ref: {'user_visible_goal': '从 TaskRunContract 读取的标题'}); projector=RunMonitorProjector(event_log=None, runtime_host=SimpleNamespace(runtime_objects=store)); task=SimpleNamespace(task_run_contract_ref='rtobj:task_run_contract:demo', task_id='task:turn:hidden', execution_runtime_kind='single_agent_task'); print(projector._display_title(task, {}, lifecycle='running'))"
```

验收结果：前端类型检查通过；后端在固定 `127.0.0.1:8003` 以新进程启动；`/api/agent-control-network`、`/api/harness/run-monitor`、`/api/harness/run-monitor/management` 和前端 `/agent-network` 均返回 200；monitor 标题投影验证输出 `从 TaskRunContract 读取的标题`。

用户已确认开始实施。后续如果发现计划假设错误、风险显著扩大、或需要改变 runtime 主权威，必须暂停修订计划再继续。

已采用的确认口径：

```text
同意按 harness runtime topology 清洗计划实施。
允许删除或降级旧 heuristic / static graph / legacy cache ledger / continuation recovery authority。
旧代码只在有明确迁移期限和只读诊断价值时临时保留。
不新增测试文件；使用静态审查、编译检查、固定端口真实运行和真实缓存日志验收。
```
