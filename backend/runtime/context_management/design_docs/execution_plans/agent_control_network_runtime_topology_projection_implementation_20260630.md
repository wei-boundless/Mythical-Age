# Agent Network Runtime Topology Projection Implementation

创建日期：2026-06-30

状态：Phase 1/2 基础链路已接通；缓存健康旧口径与 baseline/stability 双账本已完成主链路清洗，待固定端口运行复核。

## 1. 实施裁决

本轮没有新增第二套 runtime owner。`/agent-network` 被实现为：

```text
SingleAgentRuntimeHost / AgentRuntimeServices / RuntimeGateway / TurnMemoryStore / ProviderCacheBus
-> harness.runtime.context_contract.inspection_payload.build_runtime_topology_projection
-> GET /api/agent-control-network
-> frontend /agent-network inspector
```

页面名称仍可叫 Agent 控制网络，但代码权威是 `runtime_topology_projection`。它只读运行脊柱，不决定 intent、不授权工具、不组 prompt、不写 TurnMemory、不提交输出。

## 2. 文件索引

| 文件 | 动作 | 权威边界 |
| --- | --- | --- |
| `backend/harness/runtime/context_contract/inspection_payload.py` | 新增 `build_runtime_topology_projection()` | 只读投影 builder |
| `backend/harness/runtime/context_contract/diagnostics.py` | 新增 runtime topology 结构诊断 | 只检查断边/重复/缺 authority |
| `backend/harness/runtime/context_contract/__init__.py` | 导出 builder | 不创建新 owner |
| `backend/api/agent_control_network.py` | 新增 API router | 只通过 `require_runtime()` 读取 AppRuntime |
| `backend/app.py` | 挂载 `/api/agent-control-network` | 与现有 API prefix 一致 |
| `frontend/src/lib/api/types.ts` | 新增 topology payload 类型 | 前端只消费 contract |
| `frontend/src/lib/api/agentNetwork.ts` | 新增 API client | 不做本地 authority 推断 |
| `frontend/src/lib/api/endpoints.ts` | 导出 agent network client | API 索引接线 |
| `frontend/src/app/agent-network/page.tsx` | 改为后端数据源 | 删除静态 core graph 权威 |
| `frontend/src/styles/09-agent-network.css` | 节点改成小点，强化关系视觉 | 节点信息留给 inspector |

## 3. API 契约

```text
GET /api/agent-control-network
GET /api/agent-control-network/session/{session_id}
```

基础接口返回设计态拓扑：

```text
schema
authority
scope
summary
branches
domains
nodes
edges
diagnostics
runtime_evidence
```

拓扑投影就是当前读模型，不引入 `schema_version`、`.v1`、`new_*` 或 `native_*` 这类分支/过渡命名。需要标识读模型身份时只使用稳定 `schema` 值，例如 `runtime_topology_projection`。

session 接口额外读取：

```text
TurnMemoryStore.session_projection()
ProviderCacheBus build_provider_cache_log_view()
context recovery package status
```

缓存展示只读取 `latest_prefix_health`、`latest_under_read_tokens`、`current_prefix_covered` 和 `first_missing_expected_prefix_identity`。总 hit rate 只保留在 provider cache log 中作为辅助字段，不能成为健康裁决。

## 4. 当前核心节点

当前 topology projection 固定输出 harness 主干节点：

```text
HarnessRuntimeFacade
SingleAgentRuntimeHost
AgentRuntimeServices
RequestFacts
CurrentWorkBoundary
run_single_agent_turn
RuntimeCompiler
ContextPipeline
PhysicalContextPlan
PhysicalContextAssembler
ModelRuntime
ProviderPayloadManifest
ProviderCacheBus
RuntimeGateway
ModelActionLifecycle
AdmissionDecision
ActionPermit
RuntimeToolControlPlane
OutputCommitAuthority
ProviderVisibleLedger
PhysicalPrefixFrameLedger
TurnMemoryStore
TurnMemoryRecoveryContext
```

前端节点已改为小型网络点。节点不再承载大量文本；文本、authority、payload identity、failure route、cache expectation 都进入 inspector。

## 5. 连线矩阵

| edge | producer -> consumer | payload identity | authority | status |
| --- | --- | --- | --- | --- |
| `facade-to-host` | `HarnessRuntimeFacade` -> `SingleAgentRuntimeHost` | `runtime_host.instance_id` | `harness.entrypoint.runtime_facade` | connected |
| `host-to-services` | `SingleAgentRuntimeHost` -> `AgentRuntimeServices` | host service refs | `harness.runtime.services` | connected |
| `facade-to-request-facts` | API request -> `RequestFacts` | `session_id + turn_id` | `harness.runtime.request_facts` | connected |
| `request-facts-to-boundary` | `RequestFacts` -> `CurrentWorkBoundary` | `turn_id + active work ref` | `harness.entrypoint.current_work_boundary` | connected |
| `boundary-to-loop` | `CurrentWorkBoundary` -> `run_single_agent_turn` | `turn_id + runtime_branch` | `harness.entrypoint.runtime_facade` | connected |
| `loop-to-turn-memory` | `run_single_agent_turn` -> `TurnMemoryStore` | `session_id + turn_id` | `runtime.turn_memory.store` | connected |
| `loop-to-compiler` | `run_single_agent_turn` -> `RuntimeCompiler` | `packet_id + turn_run_id` | `harness.runtime.compiler` | connected |
| `compiler-to-context-pipeline` | `RuntimeCompiler` -> `ContextPipeline` | context assembly id | `runtime.context_management.context_pipeline` | connected |
| `context-pipeline-to-physical-plan` | `ContextPipeline` -> `PhysicalContextPlan` | segment id + prefix identity | `runtime.context_management.physical_context_plan` | connected |
| `physical-plan-to-assembler` | `PhysicalContextPlan` -> `PhysicalContextAssembler` | frame id + current append hash | `runtime.context_management.physical_context_assembler` | connected |
| `assembler-to-provider-payload` | `PhysicalContextAssembler` -> `ProviderPayloadManifest` | manifest ref + transport hash | `runtime.model_gateway.provider_payload` | connected |
| `compiler-to-gateway-evidence` | packet evidence -> `RuntimeGateway` | packet ref | `harness.runtime.runtime_gateway` | connected |
| `compiler-to-model-runtime` | packet -> `ModelRuntime` | request id + turn run id | `harness.loop.model_action_runtime` | connected |
| `model-runtime-to-provider-payload` | provider request -> `ProviderPayloadManifest` | manifest ref | `runtime.model_gateway.provider_payload` | connected |
| `provider-payload-to-cache-bus` | manifest/cache usage -> `ProviderCacheBus` | bus record id + request id + spine hash | `runtime.prompt_accounting.provider_cache_bus` | connected |
| `model-runtime-to-turn-memory` | provider refs -> `TurnMemoryStore` | session + turn + request ref | `runtime.turn_memory.store` | connected |
| `model-runtime-to-action-lifecycle` | provider response -> `ModelActionLifecycle` | action request ref | `harness.loop.model_action_protocol` | connected |
| `action-lifecycle-to-admission` | model action -> `AdmissionDecision` | action request ref | `harness.loop.admission` | connected |
| `admission-to-permit` | admission -> `ActionPermit` | permit id + action ref | `harness.loop.action_permit` | connected |
| `permit-to-tool-control` | permit -> `RuntimeToolControlPlane` | invocation + tool + permit | `runtime.tool_runtime.tool_control_plane` | connected |
| `tool-control-to-loop` | tool observation -> loop | invocation + observation id | `harness.loop.single_agent_turn` | connected |
| `loop-to-output-commit` | final answer -> `OutputCommitAuthority` | run + turn + message ref | `harness.runtime.output_commit_authority` | connected |
| `output-commit-to-turn-memory` | commit receipt -> `TurnMemoryStore` | session + turn + commit event | `runtime.turn_memory.store` | connected |
| `provider-success-to-visible-ledger` | provider success -> `ProviderVisibleLedger` | provider request ref + content hash | `runtime.context_management.provider_visible_context_ledger` | connected |
| `visible-ledger-to-prefix-frame` | sealed Past -> `PhysicalPrefixFrameLedger` | physical prefix frame id | `runtime.context_management.physical_prefix_frame_ledger` | connected |
| `prefix-frame-to-assembler` | confirmed frame -> assembler | frame id + frame hash | `runtime.context_management.physical_prefix_frame_ledger` | connected |
| `turn-memory-to-recovery` | TurnMemory -> recovery context | latest turn + checkpoint hash | `runtime.turn_memory.recovery_context` | connected |
| `recovery-to-facade` | recovery context -> next session context | session + recoverable turn | `harness.entrypoint.runtime_facade` | connected |

## 6. 前端行为

`/agent-network` 现在：

- 从后端读取 core nodes / edges。
- 不再内置 `CORE_NODES` / `CORE_EDGES` 作为权威。
- localStorage 只保存 `notes`，不保存 core node/edge。
- 节点以小点呈现，关系由线、左侧边列表和右侧 edge inspector 表达。
- session id 输入框只影响 session evidence，不改变 core topology。
- 右侧 inspector 展示 cache 连接证据：ContextContract node refs、edge refs、connection refs、agent domains、cache spine 和 first missing identity；这些字段来自后端 `cache_diagnostics`，前端不重算 cache verdict。
- 右侧 edge inspector 展示后端返回的 `edge_kind`、`connection_contract_ref`、`physical_lane`、`terminal_behavior`、`forbidden_route`；前端只渲染，不按文字重新分类连接。

## 7. 清洗进度

只读投影和前端接线已经完成，后续清洗按主计划继续推进。当前状态：

1. ~~`runtime_facade.py` 与 `compiler.py` 中普通 turn recovery 的 `recoverable_work` / `turn_memory_recovery` 双权威。~~ 已收口到 `TurnMemoryRecoveryContext`；普通 turn 不再投影 `recoverable_work` 模型可见恢复段。
2. ~~`app_runtime.py` 中 `cached_tokens > 0 -> warm` 的旧缓存健康口径。~~ 已由 `provider_cache_prefix_health_authority_cleanup_20260630.md` 收口：`ProviderCacheBus.current_prefix_covered`、`latest_under_read_tokens`、`latest_prefix_health.verdict` 是 warm/cold 裁决入口。
3. ~~`model_runtime.py` 对 `prompt_cache_baselines.jsonl` 和 `prompt_stability.jsonl` 的 active 写入。~~ 已由 `prefix_state.jsonl` 收口：previous/continuity/reset 只走 `PrefixStateRecord`，旧 baseline/stability ledger 方法已删除。
4. ~~`authority_rules.py` 字符串启发式分类作为主控制域来源的问题。~~ 已改为 ContextContract 标准字段适配器，缺失控制字段只报 diagnostics。
5. ~~protected old context 需要收口为 physical prefix frame replay contract。~~ 已由 `ProviderMessageReplayContract` 收口，旧 protected-context helper 已删除。
6. `ContextContractManifest.edges` 已扩展为 `agent_visible_order`、`physical_lane_projection`、`provider_payload_binding`、`cache_health_binding` 四类标准连接契约；下一步继续把 edge 级信息接入更细的 provider/cache 展示面。
7. `provider_lane` 已收口为显式接线：`model_runtime` 只从 `accounting_context.provider_lane` / `prompt_manifest.provider_lane` 解析，`context_pipeline` 只从 `model_selection.provider_lane` 读取，不再通过 `source`、`call_kind` 或 `invocation_kind` 猜 lane。
8. `ContextCapabilityProfile` 已收口为 system wiring 显式 profile：`context_capability_policy` 不再读取旧 `context_policy/memory_policy/prompt_policy` 并翻译 disabled groups，避免下游能力过滤重新裁决 runtime assembly 已经编译好的控制边界。
9. runtime topology edge 精细化已完成：`_edge()` 统一补齐 `edge_kind`、`control_signal`、`connection_contract_ref`、`physical_lane`、`producer_ref`、`consumer_ref`、`terminal_behavior`、`forbidden_route`。当前 28 条边覆盖 14 类 edge kind：`runtime_binding`、`request_observation`、`boundary_decision`、`turn_dispatch`、`turn_memory`、`packet_assembly`、`context_splice`、`provider_transport`、`cache_health`、`action_authorization`、`tool_execution`、`output_commit`、`prefix_replay`、`recovery`。API 验收显示缺失精细字段数为 0。

## 8. 验收命令

```powershell
python -m py_compile backend/harness/runtime/context_contract/inspection_payload.py backend/harness/runtime/context_contract/diagnostics.py backend/api/agent_control_network.py backend/app.py
cd frontend; npx tsc --noEmit
$payload = Invoke-RestMethod -Uri 'http://127.0.0.1:8003/api/agent-control-network'; $missing = @($payload.edges | Where-Object { -not $_.edge_kind -or -not $_.connection_contract_ref -or -not $_.terminal_behavior -or -not $_.forbidden_route }); $missing.Count
```

固定端口实测：

```text
http://127.0.0.1:8003/api/agent-control-network
http://127.0.0.1:8003/api/agent-control-network/session/<session_id>
http://127.0.0.1:3000/agent-network
```

## 9. 不变量

```text
没有第二 runtime owner
没有第二 tool authorization path
没有第二 assistant final commit path
没有前端自造 core graph authority
没有用总 hit rate 替代 expected prefix coverage
没有在控制网络主链路里引入 schema_version/.v1/new/native 分支命名
runtime topology projection 只读
```
