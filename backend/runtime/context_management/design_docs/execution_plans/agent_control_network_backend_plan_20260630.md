# Agent Network Read-Only Projection Backend Implementation Plan

创建日期：2026-06-30

状态：执行中。2026-06-30 已按用户确认开始实施 Phase 1/2：后端只读 runtime topology projection 与前端 `/agent-network` 后端接线。

2026-06-30 harness 审查修订：`harness` 已经存在真实 runtime/control spine。本文不再设计任何新的后端运行中枢，只设计读取现有 `SingleAgentRuntimeHost`、`AgentRuntimeServices`、`RuntimeGateway`、`RuntimeEventLog`、`RuntimeCompiler`、`OutputCommitAuthority`、`TurnMemoryStore` 的 inspection facade。

## 1. 目标

把当前 `/agent-network` 前端静态图改造成后端权威只读网络：

```text
真实 runtime/control/context/cache/memory 能力
-> harness runtime topology projection
-> API graph payload
-> frontend inspector
```

这里的“网络”不是新的执行框架，也不是新的运行中枢。正式工程命名优先使用：

```text
RuntimeTopologyProjection
RuntimeTopologyEdge
RuntimeAuthorityNode
ControlSignal
FeedbackRoute
```

`AgentControlNetwork` 只作为 `/agent-network` 页面和 API route 的用户可见标签，不能成为新的 Python runtime owner。

目标产物：

- 后端能返回真实节点和真实连线。
- 每条连线必须有 producer、payload、authority、consumer、failure route。
- 前端从后端读取网络，不再把静态图当权威。
- 缓存诊断以 `ProviderCacheBus` 的 latest prefix health 为准，不再用总 hit rate 当裁决。
- 不新造第二套 TurnMemory、prompt cache、physical context 或 runtime loop。

## 2. 当前源码事实

### 2.1 API 挂载

源码：

```text
backend/app.py
backend/api/deps.py
frontend/src/lib/api/client.ts
frontend/src/app/api/[...path]/route.ts
```

事实：

- 后端所有业务路由都由 `backend/app.py` 以 `/api` prefix 挂载。
- API 读取 runtime 的统一入口是 `api.deps.require_runtime()`。
- 前端固定 API base 为 `http://127.0.0.1:8003/api`。
- Next 代理也固定转发到 `http://127.0.0.1:8003/api`。

结论：新增路由应是独立只读 router，例如：

```text
GET /api/agent-control-network
GET /api/agent-control-network/session/{session_id}
```

### 2.2 现有前端图谱仍是静态权威

源码：

```text
frontend/src/app/agent-network/page.tsx
frontend/src/styles/09-agent-network.css
```

事实：

- 2026-06-30 Phase 1/2 前，页面内置 `CORE_NODES` / `CORE_EDGES`；当前已移除静态 core graph 权威。
- 用户补充内容写入浏览器 `localStorage`。
- 页面已经表达了正确方向，但数据不是后端权威。

结论：前端应保留布局和 inspector，数据源切到 backend payload；`localStorage` 只能作为临时用户注释，不参与网络裁决。

### 2.3 Context 物理拼接主干已经存在

源码：

```text
backend/runtime/context_management/context_segment_registry.py
backend/runtime/context_management/context_segment_policy.py
backend/runtime/context_management/context_pipeline.py
backend/runtime/context_management/physical_context_plan.py
backend/runtime/context_management/physical_context_assembler.py
```

事实：

- `context_segment_registry.py` 是 kind 声明集合。
- `context_segment_policy.py` 把 kind/spec 映射到四段物理结构和 commit/replay/cache 策略。
- `context_pipeline.py` 是当前 context 拼接主干：candidate -> capability filter -> provider-visible ledger -> physical plan。
- `physical_context_assembler.py` 明确规定唯一拼接顺序：

```text
static_prefix
-> confirmed old physical frame
-> current append
-> dynamic tail
```

结论：`/agent-network` 的后端投影不应重写拼接算法，只应把这条真实链路变成可检查网络。

### 2.4 ContextContract 已切到显式控制字段

源码：

```text
backend/harness/runtime/context_contract/nodes.py
backend/harness/runtime/context_contract/manifest.py
backend/harness/runtime/context_contract/authority_rules.py
backend/harness/runtime/context_contract/diagnostics.py
backend/harness/runtime/context_contract/inspection_payload.py
```

事实：

- `ContextContractNode` 已记录 `agent_domain`、`agent_role`、`control_layer`、`time_scope`、`control_signal`、`feedback_route`、`physical_lane`、`cache_expectation`、`connection_contract_ref`、`provider_payload_segment_ref`。
- `authority_rules.py` 只消费 `context_segment_registry`、`context_segment_policy`、physical lane 和 prefix identity 来归一化显式 control contract。
- `manifest.py` 已从单一 agent-visible order edge 扩展为 context contract edge 集合：`agent_visible_order`、`physical_lane_projection`、`provider_payload_binding`、`cache_health_binding`。

结论：后端网络只读 projection 已经能读取 ContextContract 的控制字段；ContextContractManifest 自身也开始输出标准连接契约，后续重点是把这些 edge 与 provider/cache 日志展示继续对齐，而不是恢复旧 semantic 层级。

### 2.5 Provider payload 和 ProviderCacheBus 已是缓存事实权威

源码：

```text
backend/runtime/model_gateway/model_request.py
backend/runtime/model_gateway/provider_payload.py
backend/runtime/model_gateway/model_runtime.py
backend/runtime/prompt_accounting/provider_cache_bus.py
backend/runtime/prompt_accounting/provider_cache_bus_record.py
backend/runtime/prompt_accounting/prefix_cache_health.py
```

事实：

- `ModelRequestBuilder` 从 `segment_plan` 绑定 provider transport。
- `ProviderPayloadManifest` 记录 messages、tools、request params、transport contract、physical cache spine。
- `ProviderCacheBus` 输出 `latest_status`、`latest_prefix_health`、`latest_under_read_tokens`、`current_prefix_covered`。
- `ProviderCacheBusRecord` 已有 `physical_cache_spine_status`、`first_mismatch_segment`、`provider_under_read_tokens`。

结论：网络中的 cache branch 必须读 `ProviderCacheBus` / prefix health，不允许前端用总 hit rate 重新判断。

### 2.6 TurnMemory 是 turn 间热账本

源码：

```text
backend/runtime/turn_memory/turn_memory_models.py
backend/runtime/turn_memory/turn_memory_store.py
backend/runtime/turn_memory/turn_memory_recovery.py
backend/runtime/turn_memory/turn_memory_recovery_context.py
backend/runtime/turn_memory/turn_memory_projector.py
```

事实：

- TurnMemory 记录 provider refs、payload manifest refs、physical frame、assistant draft/final、tool round、commit/frame pending、steer refs。
- recovery 决策只覆盖运行时事务修复，如 `retry_commit`、`retry_frame_promotion`；普通中断 turn 闭合后生成 prior work memory 包，由下一 turn 只读消费。
- `api/tokens.py` 已能读取 `session_projection()`。

结论：TurnMemory 在网络中归属 `FeedbackRecoveryDomain`，只表达 Present/Future 热状态，不成为 Past 历史权威。

## 3. 推荐设计

### 3.1 后端只读投影 / inspection facade

优先复用模块：

```text
backend/harness/runtime/context_contract/inspection_payload.py
backend/harness/runtime/context_contract/diagnostics.py
```

如果现有 inspector 无法容纳 session runtime evidence，才允许在同目录新增纯只读 helper；该 helper 不持有状态、不写 ledger、不参与 prompt/runtime 决策。

职责：

- 汇总静态 runtime authority 定义。
- 把现有模块映射成网络节点。
- 把真实跨模块调用链映射成网络连线。
- 合并可选 session 运行态摘要：TurnMemory、`ProviderCacheBus`、context recovery package。
- 输出只读 graph payload。

禁止：

- 不生成 prompt。
- 不改变 context 拼接。
- 不写 TurnMemory。
- 不写 provider-visible ledger。
- 不重算 provider cache health。

### 3.2 API router

新增文件：

```text
backend/api/agent_control_network.py
```

新增挂载：

```text
backend/app.py
```

API：

```text
GET /api/agent-control-network
GET /api/agent-control-network/session/{session_id}
```

基础 endpoint 返回静态设计态网络；session endpoint 额外读取：

- TurnMemory session projection。
- Provider cache log view。
- Context recovery package status。
- 最新 prompt/cache spine 摘要。

### 3.3 Payload schema

顶层：

```json
{
  "schema": "runtime_topology_projection",
  "authority": "harness.runtime.context_contract.agent_control_network",
  "generated_at": 0.0,
  "scope": {
    "session_id": "",
    "runtime_available": true
  },
  "nodes": [],
  "edges": [],
  "domains": [],
  "diagnostics": {},
  "runtime_evidence": {}
}
```

节点：

```json
{
  "id": "physical-context-plan",
  "title": "PhysicalContextPlan",
  "kind": "physical",
  "agent_domain": "PhysicalLaneDomain",
  "agent_role": "physical_lane_allocator",
  "control_layer": "physical",
  "time_scope": "Self/Past/Present/Future",
  "authority": "runtime.context_management.physical_context_plan",
  "module": "backend/runtime/context_management/physical_context_plan.py",
  "owned_signals": ["route_physical"],
  "state_read_policy": "read context segment policy metadata",
  "state_write_policy": "write physical lane metadata only",
  "prompt_projection_key": "",
  "physical_lane_policy": "global_static_prefix/provider_visible_context_prefix/current_turn_tail/never_replay_tail",
  "status": "connected"
}
```

连线：

```json
{
  "id": "physical-plan-to-provider-payload",
  "source": "physical-context-plan",
  "target": "provider-payload-manifest",
  "edge_type": "transport_edge",
  "signal": "serialize",
  "payload_schema": "message specs + segment bindings + physical lane metadata",
  "authority": "runtime.model_gateway.model_request",
  "lifecycle": "provider_request",
  "cache_expectation": "expected_read only for static prefix and confirmed frame replay",
  "state_read_policy": "read segment_plan and provider transport inputs",
  "state_write_policy": "write ProviderPayloadManifest only",
  "failure_route": "unplanned message -> never_cache segment and diagnostics",
  "diagnostics_key": "provider_payload_manifest_ref",
  "status": "connected"
}
```

### 3.4 固定节点集合

第一版后端网络固定输出这些节点：

| node id | 真实模块 | domain |
| --- | --- | --- |
| `request-facts` | `backend/harness/runtime/request_facts.py` | `TaskDomain` |
| `dynamic-context-manager` | `backend/harness/runtime/dynamic_context/manager.py` | `RuntimeBoundaryDomain` |
| `turn-operating-contract` | `backend/harness/runtime/turn_operating_contract.py` | `ActionHorizonDomain` |
| `context-segment-registry` | `backend/runtime/context_management/context_segment_registry.py` | `AgentControlDomainRegistry` |
| `context-segment-policy` | `backend/runtime/context_management/context_segment_policy.py` | `PolicyDomain` |
| `context-pipeline` | `backend/runtime/context_management/context_pipeline.py` | `ContextPipelineDomain` |
| `context-contract-manifest` | `backend/harness/runtime/context_contract/manifest.py` | `AgentControlDomain` |
| `prompt-projection` | `backend/harness/runtime/compiler.py` | `ProjectionDomain` |
| `physical-context-plan` | `backend/runtime/context_management/physical_context_plan.py` | `PhysicalLaneDomain` |
| `physical-context-assembler` | `backend/runtime/context_management/physical_context_assembler.py` | `PhysicalLaneDomain` |
| `model-request-builder` | `backend/runtime/model_gateway/model_request.py` | `TransportDomain` |
| `provider-payload-manifest` | `backend/runtime/model_gateway/provider_payload.py` | `TransportDomain` |
| `provider-visible-ledger` | `backend/runtime/context_management/provider_visible_context_ledger.py` | `EvidenceTimelineDomain` |
| `physical-prefix-frame-ledger` | `backend/runtime/context_management/physical_prefix_frame_ledger.py` | `EvidenceTimelineDomain` |
| `provider-cache-bus` | `backend/runtime/prompt_accounting/provider_cache_bus.py` | `CacheDiagnosticDomain` |
| `turn-memory-store` | `backend/runtime/turn_memory/turn_memory_store.py` | `FeedbackRecoveryDomain` |
| `turn-memory-recovery-context` | `backend/runtime/turn_memory/turn_memory_recovery_context.py` | `FeedbackRecoveryDomain` |

### 3.5 固定连线集合

第一版必须输出这些 edge：

| edge id | source -> target | authority | status |
| --- | --- | --- | --- |
| `request-to-dynamic-context` | RequestFacts -> DynamicContextManager | `harness.runtime.compiler` | connected |
| `dynamic-context-to-turn-contract` | DynamicContextManager -> TurnOperatingContract | `harness.runtime.turn_operating_contract` | connected |
| `registry-to-policy` | ContextSegmentRegistry -> ContextSegmentPolicy | `runtime.context_management.context_segment_policy` | connected |
| `policy-to-pipeline` | ContextSegmentPolicy -> ContextPipeline | `runtime.context_management.context_pipeline` | connected |
| `pipeline-to-ledger` | ContextPipeline -> ProviderVisibleLedger | `runtime.context_management.context_pipeline.provider_visible_context_ledger` | connected |
| `pipeline-to-physical-assembler` | ContextPipeline -> PhysicalContextAssembler | `runtime.context_management.context_pipeline.provider_visible_context_ledger` | connected |
| `physical-assembler-to-frame` | PhysicalContextAssembler -> PhysicalPrefixFrameLedger | `runtime.context_management.physical_context_assembler` | connected |
| `pipeline-to-physical-plan` | ContextPipeline -> PhysicalContextPlan | `runtime.context_management.context_pipeline.physical_context_assembly` | connected |
| `physical-plan-to-segment-plan` | PhysicalContextPlan -> PromptSegmentPlan | `harness.runtime.compiler` | connected |
| `segment-plan-to-model-request` | PromptSegmentPlan -> ModelRequestBuilder | `runtime.model_gateway.model_request` | connected |
| `model-request-to-provider-payload` | ModelRequestBuilder -> ProviderPayloadManifest | `runtime.model_gateway.provider_payload` | connected |
| `provider-payload-to-cache-bus` | ProviderPayloadManifest -> ProviderCacheBus | `runtime.prompt_accounting.provider_cache_bus` | connected |
| `provider-success-to-ledger` | ModelRuntime provider success -> ProviderVisibleLedger | `runtime.context_management.provider_visible_context_ledger` | connected |
| `provider-success-to-frame` | ModelRuntime provider success -> PhysicalPrefixFrameLedger | `runtime.context_management.physical_prefix_frame_ledger` | connected |
| `provider-request-to-turn-memory` | ModelRuntime -> TurnMemoryStore | `runtime.turn_memory.store` | connected |
| `turn-memory-to-recovery` | TurnMemoryStore -> TurnMemoryRecoveryContext | `runtime.turn_memory.recovery_context` | connected |
| `recovery-to-dynamic-context` | TurnMemoryRecoveryContext -> DynamicContextManager/compiler | `harness.runtime.compiler.turn_memory_recovery` | connected |

### 3.6 Runtime evidence

`GET /api/agent-control-network/session/{session_id}` 额外返回：

```json
{
  "runtime_evidence": {
    "turn_memory": {
      "available": true,
      "latest_turn": {},
      "active_or_pending_turns": []
    },
    "provider_cache_log": {
      "summary": {
        "latest_status": "",
        "current_prefix_covered": false,
        "latest_under_read_tokens": 0,
        "current_cache_spine_hash": ""
      }
    },
    "cache_diagnostics": {
      "verdict": "",
      "first_missing_expected_prefix_identity": {}
    }
  }
}
```

这部分只读现有 API/service，不重新计算缓存健康。

## 4. 分阶段实施

### Phase 1：后端 read-only projection 和 API

实施状态：已落地基础链路，详见 `agent_control_network_runtime_topology_projection_implementation_20260630.md`。

涉及文件：

```text
backend/harness/runtime/context_contract/inspection_payload.py
backend/harness/runtime/context_contract/diagnostics.py
backend/api/agent_control_network.py
backend/app.py
```

动作：

- 扩展现有 inspection/diagnostics，输出 plain dict read model。
- 输出固定节点和固定连线。
- session endpoint 读取 `require_runtime()`。
- 复用 `build_provider_cache_log_view()` 和 TurnMemory `session_projection()`。
- API 出错时返回结构化 diagnostics，不吞成空图。

完成标准：

- `GET /api/agent-control-network` 返回所有固定节点和连线。
- `GET /api/agent-control-network/session/{session_id}` 能返回 runtime evidence。
- 不修改 prompt/runtime 执行结果。

### Phase 2：前端切到后端数据

实施状态：已落地基础链路，详见 `agent_control_network_runtime_topology_projection_implementation_20260630.md`。节点已收缩为网络点，页面重点转为连线关系和 inspector。

2026-06-30 继续更新：`/agent-network` inspector 已增加“缓存连接证据”，直接展示后端 `cache_diagnostics` 中的 `current_context_contract_node_refs`、`current_context_contract_edge_refs`、`current_connection_contract_refs`、`current_agent_domains`、cache spine 和 first missing identity。前端只读后端字段，不重新裁决 cache health。

涉及文件：

```text
frontend/src/lib/api/types.ts
frontend/src/lib/api/agentNetwork.ts
frontend/src/app/agent-network/page.tsx
```

动作：

- 增加 TypeScript 类型。
- 页面加载时请求 `/agent-control-network`。
- 如果 URL 有 session query，则请求 session endpoint。
- 静态 `CORE_NODES` / `CORE_EDGES` 已删除，不再作为加载失败 fallback；加载失败必须显式显示错误。
- inspector 展示 edge 的标准字段：payload_schema、authority、lifecycle、cache_expectation、state_read_policy、state_write_policy、failure_route、diagnostics_key。
- inspector 展示 session cache 连接证据：ContextContract node refs、edge refs、connection refs、agent domains 和 first missing identity。

完成标准：

- 页面显示后端返回的 node/edge 数量。
- localStorage 补充只作为用户注释，不参与 core graph。
- 前端不重新判断 cache health。

### Phase 3：把 ContextContractManifest 与网络对齐

涉及文件：

```text
backend/harness/runtime/context_contract/nodes.py
backend/harness/runtime/context_contract/manifest.py
backend/harness/runtime/context_contract/diagnostics.py
backend/harness/runtime/context_contract/inspection_payload.py
```

动作：

- 在只读网络稳定后，为 `ContextContractNode` 补齐显式控制字段：

```text
agent_domain
agent_role
control_layer
time_scope
primary_control_signal
feedback_route
prompt_projection_key
physical_lane
cache_expectation
connection_contract_ref
```

- 先由显式映射填充，不能继续依赖字符串猜测。
- `authority_rules.py` 降级为读取 explicit contract 的适配器；缺失时只报 diagnostics。
- `ContextContractEdge` 补齐 `edge_id`、`payload_identity`、`payload_schema`、`transport_or_store`、`consumer`、`failure_route`、`cache_expectation`、`connection_contract_ref`、`physical_lane`、`control_signal`。
- `manifest.py` 输出 `agent_visible_order`、`physical_lane_projection`、`provider_payload_binding`、`cache_health_binding` 四类边。
- `diagnostics.py` 校验 edge endpoint、authority、payload identity、payload schema、connection contract 和 provider/cache target。

完成标准：

- ContextContract inspection 能解释每个 node 属于哪个 domain/signal/route。
- ContextContract inspection 能按 edge_kind、edge authority、physical lane、connection contract 分组。
- 旧启发式不再参与主运行路由。

### Phase 4：ProviderPayloadManifest 回指 contract node

实施状态：已完成第一段身份链补线，并已接入 edge identity。`PromptSegmentPlan` 从 `ContextContract` 权威分类写入 `context_contract_node_ref`、`context_contract_edge_refs`、`agent_domain`、`control_signal`、`connection_contract_ref`、`cache_expectation`；`ProviderPayloadSegment`、`CachePlanRecord` diagnostics、`PrefixCacheHealth.first_missing_expected_prefix_identity`、`ProviderCacheBusRecord` 与 `provider_cache_log` 会沿同一身份链输出。缓存断点现在可以直接回指到 agent 控制域、contract node 和具体 connection edge，不再只剩 segment id/hash。

涉及文件：

```text
backend/runtime/model_gateway/provider_payload.py
backend/runtime/model_gateway/model_request.py
backend/runtime/prompt_accounting/provider_cache_bus.py
backend/runtime/prompt_accounting/cache_planner.py
backend/runtime/prompt_accounting/prefix_cache_health.py
backend/harness/runtime/prompt_segment_plan.py
backend/harness/runtime/context_contract/authority_rules.py
```

动作：

- `PromptSegmentPlan` metadata 增加 `context_contract_node_ref` 和 `context_contract_edge_refs`。
- ProviderPayloadSegment 增加 `context_contract_node_ref`、`context_contract_edge_refs`、`connection_contract_ref`、`agent_domain`、`control_signal`、`cache_expectation`。
- `ProviderCacheBus` latest first break 输出 `agent_domain`、`physical_lane`、`context_contract_node_ref`、`context_contract_edge_refs`。

完成标准：

- 缓存断点能定位到：agent_domain + physical lane + provider segment + ContextContract node/edge + first missing identity。
- 77.19% 这类总 hit rate 不再能覆盖 expected prefix under-read。

### Phase 5：清理旧静态图和旧弱连线

涉及文件：

```text
frontend/src/app/agent-network/page.tsx
backend/harness/runtime/context_contract/authority_rules.py
backend/runtime/context_management/design_docs/*
```

动作：

- 删除前端静态图作为主数据源。
- 清理旧 “semantic” 命名作为目标架构语言；保留历史字段事实。
- 清理未接后端的 planned edge。
- 只保留明确 diagnostics，不保留旧运行分支兼容。

完成标准：

- `/agent-network` 的 core graph 来自后端。
- 每条边都有标准连接契约。
- 搜索不到前端用静态 `CORE_NODES` / `CORE_EDGES` 当权威的路径。

## 5. 文件级清单

| 文件 | 动作 |
| --- | --- |
| `backend/harness/runtime/context_contract/inspection_payload.py` | 扩展，只读拓扑 payload |
| `backend/harness/runtime/context_contract/diagnostics.py` | 扩展，只读诊断 evidence |
| `backend/api/agent_control_network.py` | 新增 router |
| `backend/app.py` | include router |
| `frontend/src/lib/api/types.ts` | 增加 network payload 类型 |
| `frontend/src/lib/api/agentNetwork.ts` | 新增 API client |
| `frontend/src/app/agent-network/page.tsx` | 改为读取后端 graph |
| `backend/harness/runtime/context_contract/nodes.py` | 显式 contract node 字段和标准 edge 字段 |
| `backend/harness/runtime/context_contract/manifest.py` | 生成 order / physical lane / provider payload / cache health edge |
| `backend/runtime/model_gateway/provider_payload.py` | 后续 provider segment 回指 |
| `backend/runtime/prompt_accounting/provider_cache_bus.py` | 后续 cache anomaly 回指 agent domain |

## 6. 设计不变量

1. `PhysicalContextPlan` 仍是四段物理权威。
2. `ProviderPayloadManifest` 仍是 provider request 和 hidden transport 权威。
3. `ProviderCacheBus` 仍是前端 cache health 展示权威。
4. `TurnMemory` 仍是 Present/Future 热账本，不写 sealed history。
5. `ProviderVisibleLedger` / `PhysicalPrefixFrameLedger` 仍是 Past 权威。
6. 前端不重新解释 runtime authority。
7. runtime topology projection 是 read model，不是第二套 runtime。
8. hidden transport 不进入 agent-visible prompt。
9. 旧启发式可短期做 diagnostics，但不能成为新主链路。
10. 不新增测试文件；验证用编译、静态审查、固定端口真实运行。

## 7. 验证方式

按项目约束，不新增测试文件。

静态检查：

```powershell
python -m py_compile backend/harness/runtime/context_contract/inspection_payload.py backend/harness/runtime/context_contract/diagnostics.py backend/api/agent_control_network.py backend/app.py
rg -n "CORE_NODES|CORE_EDGES" frontend/src/app/agent-network/page.tsx
rg -n "agent-control-network|RuntimeTopologyProjection|AgentControlNetwork" backend frontend/src
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

真实 API 验收：

```powershell
Invoke-WebRequest -UseBasicParsing http://127.0.0.1:8003/api/agent-control-network
Invoke-WebRequest -UseBasicParsing http://127.0.0.1:8003/api/agent-control-network/session/<session_id>
Invoke-WebRequest -UseBasicParsing http://127.0.0.1:3000/agent-network
```

页面验收：

- 网络节点数和连线数来自 backend payload。
- inspector 显示每条 edge 的 authority/failure route/cache expectation。
- cache branch 显示 latest prefix covered / under-read，不显示“总 hit rate 即健康”的判断。
- cache branch 显示 ContextContract node/edge refs，不由前端重新推断连接关系。
- TurnMemory branch 显示 latest turn 和 recovery decision 摘要。

## 8. 禁止事项

- 禁止把前端静态图继续当权威。
- 禁止新增一套和 `context_pipeline.py` 并行的拼接系统。
- 禁止让 runtime topology projection 写入 ledger 或 TurnMemory。
- 禁止把 hidden transport 字段投影成 agent-visible prompt。
- 禁止用总 hit rate 替代 expected prefix coverage。
- 禁止为了兼容保留旧启发式作为主运行分支。
- 禁止新增测试文件或用 mock 绕过真实链路。

## 9. 推荐裁决

建议按 Phase 1 到 Phase 2 先完成“真实后端只读投影 + 前端读取后端”。

这一步不会改变 agent 执行语义，风险低，但能立刻让我们看到真实连线：

```text
RequestFacts
-> DynamicContextManager
-> TurnOperatingContract
-> ContextPipeline
-> PhysicalContextPlan
-> ModelRequestBuilder
-> ProviderPayloadManifest
-> ProviderCacheBus
-> ProviderVisibleLedger / PhysicalPrefixFrameLedger
-> TurnMemory
-> RecoveryContext
```

只读网络已稳定接入；Phase 3 已完成主字段收口，并已把 `ContextContractManifest.edges` 扩展为标准连接契约；Phase 4 已完成 `context_contract_node_ref/context_contract_edge_refs` 到 provider payload/cache bus 的身份链。后续继续优化展示和清理旧链路。

