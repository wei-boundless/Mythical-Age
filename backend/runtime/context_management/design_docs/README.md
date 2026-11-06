# Context Management Design Docs Index

本目录保存 agent runtime、上下文拼接、provider cache、TurnMemory、能力系统和执行链路的设计资料。这里是文档索引，不是单篇计划堆放区。

## 当前主线

当前大工程以 harness 真实运行脊柱为准，不新造第二套 runtime owner。

| 优先级 | 文档 | 用途 |
| --- | --- | --- |
| P0 | `execution_plans/harness_runtime_spine_authority_index_20260630.md` | 当前 harness 主脊柱、权力链路、关键连线和文档索引 |
| P0 | `execution_plans/agent_control_network_architecture_cleanup_plan_20260630.md` | 大清洗分阶段计划，后续实施按此分片 |
| P0 | `execution_plans/agent_control_network_backend_plan_20260630.md` | `/agent-network` 后端只读投影和前端接线计划 |
| P0 | `execution_plans/agent_control_network_runtime_topology_projection_implementation_20260630.md` | 本轮 Phase 1/2 实施记录、接口契约、文件索引和后续清洗边界 |
| P0 | `execution_plans/prompt_accounting_ledger_layering_optimization_plan_20260630.md` | prompt accounting 账本分层、prefix_state、provider_cache_bus 和旧账本清洗计划 |
| P0 | `execution_plans/provider_cache_prefix_health_authority_cleanup_20260630.md` | 缓存健康裁决清洗：ProviderCacheBus / prefix health 取代 `cached_tokens > 0` |
| P0 | `execution_plans/turn_heartbeat_hot_journal_rewrite_recover_steer_authority_plan_20260629.md` | TurnMemory 热账本、recover、steer、commit pending 的设计依据 |
| P0 | `execution_plans/context_prefix_authority_unification_refactor_plan_20260629.md` | prefix identity、四段物理模型和缓存命中裁决的设计依据 |
| P0 | `execution_plans/system_asset_line_governance_optimization_plan_20260701.md` | 当前 SystemAssetLine / ContextLineState / ContextCandidateGateway / ControlOutputLine / agent-control-network 线路治理权威 |
| P0 | `cache_prefix_hit_audit_report_20260629.md` | 最新缓存命中问题分析，强调前缀命中而不是总 hit rate |
| P0 | `cache_prefix_identity_format_audit_report_20260629.md` | prefix 格式、身份标识和成熟 agent 对比报告 |

## 基础参考

| 文档 | 用途 |
| --- | --- |
| `execution_plans/harness_neural_system_consolidation_plan_20260628.md` | harness 控制体系收束、分集和 graph system 独立的早期总方案 |
| `execution_plans/total_neural_architecture_audit_20260628.md` | 后端总架构审计，作为历史边界参考 |
| `execution_plans/system_ownership_directory_audit_20260628.md` | 项目目录和后端一级系统归属 |
| `execution_plans/backend_code_structure_semantic_refactor_plan_20260628.md` | 代码结构迁移参考，不能覆盖 harness runtime spine |
| `execution_plans/agent_lifecycle_output_channel_contract_design_20260628.md` | Agent 生命周期、输出通道、final answer commit 基准 |
| `execution_plans/provider_payload_physical_cache_spine_authority_plan_20260628.md` | Provider payload physical cache spine 权威 |
| `execution_plans/provider_tool_protocol_cache_spine_governance_20260629.md` | Provider-native 工具协议轮与 cache spine 原子结构 |
| `execution_plans/physical_context_spine_authority_unification_plan_20260629.md` | 物理拼接、frame 继承、follow-up/initial 统一装配 |
| `semantic_space/current_context_line_map_20260629.md` | 语义空间、provider-visible 账本、物理 lane 和 cache spine 连线图 |
| `execution_plans/context_pipeline_standardization_refactor_plan.md` | 上下文流水线和物理拼接计划 |
| `capability_tools/capability_system_standardization_plan_20260627.md` | Tools / MCP / Skills 能力系统计划 |

## 目录分层

- `execution_plans/`：runtime、harness、TurnMemory、cache、task mode、代码结构迁移计划。
- `semantic_space/`：历史语义空间研究和术语演化记录；只作参考和证据，不覆盖当前 `SystemAssetLine -> ContextLineState -> ContextCandidateGateway -> PhysicalContextInputs` 主链。
- `capability_tools/`：工具契约、provider tools、MCP、Skills、能力供给。
- `cache_provider/`：prompt cache、DeepSeek/provider adapter、prefix envelope、provider-visible context 策略。

## 维护规则

- 大规模 runtime/context/memory/API 改动必须先更新对应计划文档，再实施。
- 新文档必须挂到本索引；没有进入索引的文档不能作为实施权威。
- `/agent-network` 是只读诊断投影，不是第二 runtime owner。
- `RuntimeGateway` 是 control fact gateway，不能被写成 intent/permission/tool/commit owner。
- `TurnMemory` 是普通 turn 间热账本，不能和旧 continuation recovery 双权威。
- 缓存健康以 expected prefix coverage、under-read、first missing prefix identity 为准；总 hit rate 只能辅助观察。
- 新增架构文档必须归入上述四类之一，不再堆到 `context_management` 根目录。
- `design_docs` 是可追踪目录；不要使用名为 `docs` 的子目录，因为项目 `.gitignore` 会忽略它。
- 当前术语以 `SystemAssetLine`、`ContextLineState`、`ContextInputEnvelope`、`PhysicalContextInputs`、`ControlOutputLine` 为准；旧文档中的 `session memory`、`memory prefix`、`provider old context` 不能作为当前实现术语。
