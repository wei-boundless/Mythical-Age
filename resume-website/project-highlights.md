# 项目硬核清单（面试准备用）

> 每一行都有代码依据。用途：面试前复习、决定简历上写哪些。**不是简历文本。**

---

# 一、mythical-age —— 通用型 harness 智能平台

## A. 运行时内核与动作治理

**1. 动作准入的"单权威链"（双门与运算）**
一个模型动作要过两道独立裁决：`AdmissionDecision`（7 值：allow / deny / ask_approval / invalid / needs_contract / needs_task_run / operation_unavailable），再由它生成 `ActionPermit`；最终 `ActionLifecycleDecision.allowed` 的定义是 `admission.decision == "allow" AND action_permit.allowed`。代码诊断里直接写明 `single_authority_chain: admission->action_permit`。
→ **难在哪**：把"能不能做"和"允不允许执行"拆成两个独立裁决源再强制与运算，杜绝单点放行。

**2. 拒绝指纹去重 + 防"原样重试"熔断**
对 `action 身份 + 裁决 + 运行时指纹` 做 sha256 生成拒绝指纹；同一指纹 `repeat_count > 1` 时，返回 `error_code=repeated_admission_denial`，并强制给模型注入修复指令"必须停止原样重试"。
→ **难在哪**：模型被拒后最容易做的事就是原样重试。这里做了稳定指纹 + 熔断 + 强制改向，而不是简单报错。

**3. 单轮 tool-loop 的三条熔断线 + 模型自撰收口**
`_CONSECUTIVE_TOOL_FAILURE_CLOSEOUT_THRESHOLD = 3`（连续工具失败）、`_MAX_SINGLE_TURN_PROTOCOL_RECOVERY_ATTEMPTS = 3`（协议恢复尝试）、`max_tool_iterations`（工具迭代上限）。任一条触发后，不是硬杀，而是要求模型 `emit_agent_authored_closeout` 产出有证据的收口答复，terminal_reason 分别落到 `tool_budget_exhausted` / `single_turn_tool_iteration_limit` / `protocol_recovery_exhausted`。
→ **难在哪**：熔断后仍要保住交付质量，而不是给一个空白错误。

**4. 拒绝被翻译成"下一步动作"而不是错误**
`ActionAdmissionRecoveryPayload` 含 `error_code / summary / repair_instruction / structured_error{retryable, origin}`，并按状态分 needs_approval / needs_contract / denied 三套提示词。边界拒绝是模型可执行的指令，不是死胡同。

**5. 任务运行状态机（9 态 + 14 种终止原因）**
created / admitted / running / waiting_executor / waiting_approval / blocked / completed / failed / aborted；terminal_reason 含 `tool_loop_budget_exceeded`、`partial_contract_failed`、`model_response_timeout_after_partial_output` 等。**控制态必须有网关信号背书才算权威**（`runtime_gateway.signal_by_id`）。
→ **难在哪**：状态不是自说自话，控制态和业务态分离且互相校验。

**6. 人审插队的两条通道 + 运行中转向**
- 工具审批 `TaskToolApprovalGrant`：默认 ttl 3600s、`consumed` 一次性、绑定 `tool_call_id + operation_id + directive_ref + risk_fingerprint`
- 任务启动门 `TaskLaunchGatePass`：必须 pending，`allow_direct_pass` 可禁止直放
- 回合内用户转向：`claim_active_turn_queued_user_steers(limit=8)`，在 `before_model_action` 阶段注入
→ **难在哪**：审批被绑到具体调用指纹并防重放，插入点选在模型决策之前。

## B. 任务契约与任务图

**7. 声明式契约 → 编译成可执行部署包**
`ContractSpec` 含 `acceptance_rules`（7 种 rule_type：required_field_present / artifact_exists / schema_match / quality_review / model_judge / human_review / custom_runtime_check，severity ∈ error/warning/info）、`artifact_requirements`、`human_gate_policy`、`failure_policy`（retry_allowed / retry_limit / escalate_to / fallback_contract_id）、`context_visibility_policy`。编译产出 `GraphCompilationUnit`，含节点/边/资源/任务契约索引 + `deployment_package`（required_environments / required_resources / launch_contract）。
→ **难在哪**：契约 → 索引 → 部署包三段式，且编译报告能回归出未完成项。

**8. 任务图：28 种节点 × 6 执行模式 × 6 等待 × 6 汇聚**
`TASK_GRAPH_NODE_TYPES` 28；`NODE_EXECUTION_MODES` 6（sync/async/parallel/background/barrier/manual_gate）；`NODE_WAIT_POLICIES` 6；`NODE_JOIN_POLICIES` 6；边策略各 4；契约绑定段 12；运行时契约键 20（超集会 raise）。`validate_task_graph` 产出 20+ 错误码（`background_node_timeout_missing`、`barrier_node_missing_upstream` 等）。
→ **难在哪**：合法组合被编译期穷举校验，非法组合直接给错误码。

**9. 语义角色与图结构解耦**
`NodeSemanticRole` 8（producer / validator / approver / publisher / aggregator / router / resource / monitor）、`EdgeSemanticRole` 10、`RuntimeArtifactState` 7（produced → pending_validation → validated → published / rejected / superseded / quarantined）。角色由 `review_gate_policy / human_gate_policy / join_policy` **推导**并记录 evidence，旧字段逐条给 `superseded_fields` 弃用诊断。

**10. 拆分 / 验收 / 合并三段策略**
`SUPPORTED_SPLIT_MODES = {static_batch}`；验收 3 种（review_then_commit / manual_review_then_commit / auto_commit_without_review）；合并 2 种；`DEFAULT_MAX_BATCHES = 200`（超出直接报 `split_policy_max_batches_exceeded`）；`BatchAcceptancePolicy(max_repair_rounds=3, commit_visibility="next_batch_after_acceptance")`。
→ **难在哪**：批次验收后的可见性被显式建模，修复轮数封顶防震荡。

**11. 记忆的三态语义权限（预设式）**
`SEMANTIC_RELATION_PRESETS` 8 条（writing 5 + memory 3）。memory 预设分 read / write_candidate / commit：read 时 `on_missing=block`、限 50 条、只读 `status_filter=["committed"]`；commit 需 `required_verdict="pass"`、`visible_after="next_clock"`；返修 `max_revision_attempts=3`。
→ **难在哪**："候选记忆不直接对后续可见"被编码成参数+指令，不是注释。

## C. 上下文编译与缓存

**12. Provider 可见追加账本（1730 行）+ 物理前缀帧（1520 行）**
每次发往 provider 的消息切段、按 `item_key`/hash 记账，**只有 provider 成功后条目才置 `confirmed_provider_visible`**；帧记录 `transport_contract_hash`、`provider_payload_prefix_hash`、`boundary_segment_id`、`provider_tool_round_closed`。`PhysicalPrefixFrameSegment` 29 字段、`PhysicalPrefixFrame` 28 字段。
→ **难在哪**：把"模型已经看见过什么"做成可审计的前缀恒等式与回滚单元，而不是拼消息。

**13. 缓存脊柱 / 尾部车道不变量**
`CACHE_SPINE_LANES = {global_static_prefix, provider_visible_context_prefix}`，`TAIL_LANES = {current_turn_tail, never_replay_tail}`；产出 `stable_after_tail_violations`，违规码 `cache_spine_segment_after_current_turn_tail`。
→ **难在哪**：把 prompt cache 命中率显式化为车道不变量 + 违规诊断。

**14. 三入口运行时编译器（5001 行）**
`compile_semantic_compaction_packet` / `compile_single_agent_turn_packet` / `compile_observation_followup_packet`。每段带 `message_spec`：`kind` / `cache_scope` / `cache_role`（volatile / session_stable / cacheable_prefix）/ `prefix_tier` / `compression_role`（preserve / summarize / ref_only）。

**15. 增量上下文帧 + 前缀锁**
`build_prefix_lock_report` 逐条比对 `model_message_hash` / `content_hash`，产出 `role_changed` / `model_message_hash_changed` / `content_hash_changed`；工具回合的 followup 帧只发 `current_tool_round` + `unchanged_refs`（上限 4）+ `tool_context_delta`。
→ **难在哪**：工具回合只追加增量，并断言历史前缀一个字节都没变。

## D. 能力目录

**16. 三层投影 + 绑定图 + 20 条校验规则**
tool / skill / mcp 统一归一为 `CapabilityUnit`（前缀 `tool:` / `skill:` / `mcp:`）；`CapabilityBindingGraph` 含 agent_nodes / mcp_nodes / agent_tool_edges / mcp_operation_edges / recommendations。校验规则 20 条，含 `high_risk_tool_missing_approval`、**`mcp_model_visibility_invalid`（本地 MCP 必须 `not_direct_model_tool`）**、`duplicate_operation_alias`。
→ **难在哪**：把"本地 MCP 不得直接暴露给模型"写成可校验不变量。

## E. 项目网络（README 未提及的新模块）

**17. 把"读懂一个代码库"编译成可滚动的图-分片 DAG**
`ProjectNetworkLayerPlan`（layer_kind / shard_policy / aggregation_policy / validation_policy / publish_policy）；`shard_planner` 把 7 种 layer_kind 映射为 work unit；9 种 `work_unit_kind`；`ShardComplexityPolicy` 阈值 8/12/80/120，`force_single_file_modules=True`。

**18. 三种图物化模式 + 路由权威互斥**
`GraphMaterializationMode` 3（static_pre_materialized / rolling_one_hop / runtime_requested_expansion）；`NodeRouteDecision.route_authority` 4，且 `next_graph_materialization` 不得同时含静态边、必须有 `next_package_ref`（构造期强校验）。
→ **难在哪**：图在运行中"再生"，必须保证权威唯一。

## F. 可数数字（真实）

| 项 | 值 |
|---|---|
| 后端 | 1160 个 .py / 36.9 万行 / 40 个模块 |
| 前端自有代码 | 241 个文件 / 7.7 万行 |
| 测试 | 122 个测试模块 |
| git 提交 | 441 次（2026-04-07 起） |
| `TaskContract` | 45 字段 |
| 任务图节点类型 | 28 种 |
| 能力/操作 | 14 个原生工具、37 条操作定义、5 个本地 MCP 单元、2 个内置 Skill |
| 超大单文件 | `single_agent_turn.py` 487 KB（约 10618 行）、`harness/runtime/compiler.py` 5001 行 |
| 提示词资产 | 8 层 prompt layers、9 级契约优先级、54 个 guidance md |

## G. ⚠️ 不能写进简历（空壳 / 未接线）

| 说法 | 实际情况 |
|---|---|
| Agent 暂停 / 恢复 / 停止控制 | `harness/agent_control/` 只剩子 Agent 控制接口，且直接返回 `legacy_subagent_task_runner_removed` |
| 重复调用抑制 | `ToolRepetitionGuard` 只有定义与导出，生产链路无调用点 |
| 提示词引擎层 | `backend/prompting/` 目录不存在，只有 library + composition |
| A2A 协议 | `agent_system/a2a/` 仅 3 个文件 / 320 行适配器 |
| 证据驱动产物验收 | 证据接的是"答案收敛"，产物验收走另一条 Office 校验链路，两者无交叉 |
| 模型级重排 | `reranker.py` 只有 Noop 与启发式实现 |
| 工具型图节点 | `work_kind == "tool"` 直接返回 `graph_tool_node_executor_not_connected` |
| 上下文候选注册表 | `ContextCandidateRegistry` 全库无任何 contributor 实现 |

---

# 二、风起千帆 —— AI 智能写作平台

## A. 硬核点

**1. 多源运行时头的确定性恢复裁决（最硬的一条）**
`AutomationRecoveryService#assess` 交叉读 RunStore / TaskSchedulerStore / AutomationLedgerStore / AutomationCheckpointStore 四个独立持久化头，输出 **12 种唯一安全动作**（REBUILD_SCHEDULER_PROJECTION / REPLAY_RESULT_APPLICATION / FAIL_FUTURE_REVISION / REQUIRE_OPERATOR_REPAIR / WAIT_FOR_LEASE_EXPIRY 等）。重建调度投影时只从不可变 TaskPlan + ledger 重建，**丢失的 CLAIM 故意重开为 READY，已持久化的结果绝不重跑**。
→ **难在哪**：能区分"检查点落后于账本"和"检查点引用了未来修订"，不把损坏载荷误判成"记录缺失"。

**2. 检查点哈希密封 + 乐观 CAS**
`AutomationCheckpoint.next()` 强制 rounds / dispatched / ledgerRevision 单调不减、revision 用 `Math.addExact`；落库携带 `stateHash = SHA256(runId, status, rounds, dispatched, ledgerRevision, waitingReason)`，**读回重算不符即抛异常**；写入走 `compareAndSave(current.revision(), …)`。

**3. 收据信封的跨字段一致性（构造期不可违反）**
`ReceiptEnvelope`：baselineRefs 必须在 scope 的 projectId + branchId 内；SUCCEEDED 必须非空 outputRefs 且 errorCategory = NONE、errorCode 为空；REJECTED / FAILED / CONFLICTED 必须同时带类别 + 错误码；`terminal() = status != WAITING`。
→ **难在哪**：把成功语义、错误语义与幂等摘要合并成"非法态构造不出来"。

**4. 提示词即契约 + JSON Schema 双闸**
`PromptContractRenderer` 渲染时命中 FORBIDDEN 列表（数据库 / SQL / ORM / LangGraph / checkpoint / 游标 / 控制器 / 持久化 / 租约）**直接抛异常**——提示词里不许出现实现细节；`AgentOutputValidator.structured` 用 networknt JSON-Schema 2020-12，先校验 `responseJsonSchema.properties.type.const == spec.outputSchema()`，再校验模型最终输出。21 个业务输出 Schema。
→ **难在哪**：业务输出形状成为可执行契约，并把实现细节从提示词里硬性驱逐。

**5. 设计修订影响的三动作收敛协议**
`DesignRevisionImpact.Action` 三类：REVIEW_REVALIDATION / COMPLETION_REVALIDATION / SEARCH_REPROJECTION。构造器断言：`replacementRef.version() == baseRef.version() + 1`、同分支，且 **`pendingActions.size() + resolutionRefs.size() == Action.values().length`**——每个动作必须"待办或已解决"二选一，用集合基数把收敛完备性写成构造期约束。
→ **难在哪**：这是把"一个都不能漏"写成类型不变量，而不是靠流程自觉。

**6. 三类收敛的真实执行体**
- REVIEW / COMPLETION：`DesignRevisionRevalidationService`，只接受 `ReviewKind.DESIGN + Disposition.PASS + targetRef = "design-revision-review:{impactId}:v{version}"`
- SEARCH：`DesignRevisionProjectionService`，经 RetrievalProjectionOutbox，`acknowledgeCompleted` 逐字比对 documents / removed / sourceCommitRef / projectionVersion 才解除动作
→ **难在哪**："证据必须是当前那一份"被固化成 targetRef 指纹，杜绝复用旧审核。

**7. 章节影响报告 → 重确认任务链**
`ChapterImpactService#analyze` 沿 Phase 章节序向后传播，仅当 `delivery.basePreviousCandidateRef()` 等于被替换依赖才标记，`reportId = SHA256(phase|chapter|old|new|affected)`；`ChapterReconfirmationPlanner` 取叶子交付生成 expectedPreviousCandidateRef 链；`ChapterReconfirmationWorkPlanner` 编成 outline → draft → review → delivery 四任务顺序子图；`ChapterReviewGate` 限一次返修 + 二次 PASS。
→ **难在哪**：把版本血缘约束成"与上一章唯一依赖"，并按次数封顶防返修震荡。

**8. 语义事实提交的原子边界**
`NarrativeCommitService#commit` 事务内：先幂等（`sameCommand` 比对 payload + inputHash）、再校验 baseline 过期（`currentVersions != baseline.version` 抛异常）、版本取 `history.getLast() + 1`；同 objectId 跨类型直接拒绝；KnowledgeState 必须 ADOPTED 且有事件证据。
→ **难在哪**：重放安全 + 语义对象身份唯一，压进同一个原子边界。

**9. 能力幂等指纹跨 JVM 稳定 + 授权失效可恢复**
`CapabilityInputFingerprint` 用 `ORDER_MAP_ENTRIES_BY_KEYS` + `SORT_PROPERTIES_ALPHABETICALLY` 规范化后算 SHA-256；dispatch 抛 `DelegationAuthorizationException` 时 Kernel 返回 WAITING 且 `waitingReason = "AUTHORIZATION_" + reason`；恢复前 `assertActive(plan.delegationEnvelope())`。

**10. LangGraph4j 只做骨架路由，不做第二真相源**
`LangGraph4jAutomationEngine` 只有一个 `"dispatch"` 自环节点，按 status 走 dispatch / END；节点体只调 `AutomationExecutionKernel.advance`（唯一推进口）；**完全没用 LangGraph 的 CheckpointSaver**，checkpoint 由自己的 `AutomationCheckpointStore` 管。
→ **难在哪**：让编排框架不成为第二个真相源——规则全在 Kernel，框架只管路由。

## B. 可数数字（真实）

| 项 | 值 |
|---|---|
| `src/main` | 550 个 Java 文件（agent 208 + narrative 341） |
| record / enum / interface | 197 / 77 / 93（按文件计） |
| `*Service` / `*Store` | 42 / 142 |
| Jdbc* / InMemory* | 53 / 45 |
| Flyway 迁移 | 34 个（V1–V34） |
| 建表 | 72 张 |
| Agent 角色 / 提示契约 | 12 / 12 |
| 业务输出 JSON Schema | 21 个 |
| 测试文件 | 162 |

## C. ⚠️ 接线状态（**简历重大风险，必须知道**）

| 检查项 | 实际状态 |
|---|---|
| HTTP 层 | `src/main` 中 `@RestController` 命中 **0** —— 新内核没有任何对外接口 |
| 前端接谁 | `frontend/vite.config.ts` 把 `/api` 代理到 `127.0.0.1:8567`；legacy-backend 有 59 个 `@RestController`，与 `frontend/src/api` 的 26 个客户端一一对应 → **前端接的是 legacy，不是新内核** |
| 新旧耦合 | legacy 引用 `agent`/`narrative` 的文件 **0**；新内核也无 legacy import → 两套完全脱钩 |
| 持久化 | `application.yml` 里 20 个 `writing.persistence.*` **全默认 memory**；23 处 `@ConditionalOnProperty(havingValue="memory", matchIfMissing=true)`。Jdbc*（53 个）仅在显式设 `jdbc` 时才生效 |
| 数据库 | `application.yml` 无 `spring.datasource`、无 Flyway 连接配置 → **72 张表在默认路径下不被使用** |
| LLM 推理 | `LangChain4jInferenceGateway` 需要 `features.ai.enabled=true`，而**默认 false**；下游 `AgentToolLoop` / `ContextBuilder` / `ModelAgentHandler` 全是 `@ConditionalOnBean(InferenceGateway.class)` → **默认配置下模型根本不会被调用** |
| ES 检索 | 需要 `features.search.elasticsearch-enabled=true`，`application.yml` 无此配置段 → 默认关闭 |

**结论：风起千帆的新内核是一套"设计完成、领域模型与协议完整、但尚未接上线"的内核。** 代码质量与设计密度很高（契约、不变量、收敛协议都是真的），但运行层（HTTP / 持久化 / 模型调用 / 检索）默认全部关闭。

**因此简历上必须遵守的口径：**
- ✅ 可以说：设计并实现了 XX 内核、定义了 XX 协议与不变量、实现了 XX 收敛机制
- ❌ 不可以说：平台已支撑 XX 部作品 / 已上线 / 支持读写一体化 / 已跑通端到端
- ❌ 不要写"支持暂停、失败停止和中断后的继续执行"这种运行期承诺（机制在，运行链路没接）

---

# 三、怎么写（结论）

## 筛选标准（三条，缺一不写）

1. **可感知**：面试官不需要读过这份代码就能听懂价值。像"模型被拒后原样重试怎么办"，人人点头；像"checkpoint 哈希密封"，要解释半天。
2. **有对比**：能一句话说清"常规做法是什么、我为什么不一样"。例如"常规是拓扑排序，我用成果依赖判定"。
3. **在主干上**：属于核心链路，不是边缘优化。

按这三条筛选，两个项目各能留下 **5-6 条**。

## 每条的结构

```
**标签（2-6 字）：** 一句机制。一句"这解决了什么真问题"。
```

- 最多两行
- 不写字段数 / 枚举值数量（那是报告）
- 不写推理链（"而非""因此"开头的论证段删掉）
- 一条要点 = 一个面试问题入口

## 两个项目的叙事主线

- **mythical-age**：主线是「**模型不可信、所以要把边界做在运行时上**」——准入双门、拒绝熔断、熔断后自撰收口、契约编译、前缀不变量。这些合起来讲的是一个观点：Agent 的可靠性不来自提示词，来自运行时约束。
- **风起千帆**：主线是「**把业务不变量写进类型，让非法状态构造不出来**」——收据信封跨字段断言、收敛动作基数断言、检查点哈希密封、提示词驱逐实现细节。合起来讲的是：长篇写作最贵的是"改了一处、全篇失准"，所以用类型和协议把它挡在设计期。
