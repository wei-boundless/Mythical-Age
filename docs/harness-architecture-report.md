# Harness 运行时体系 — 底层架构技术报告

> 基于 `backend/harness/` 源码分析，覆盖 entrypoint、runtime、loop、continuation、graph 五大模块。
> 报告日期：2026-06-15

---

## 一、整体架构分层

```
┌─────────────────────────────────────────────────────────────┐
│                    API 入口层 (entrypoint)                    │
│  HarnessRuntimeFacade  — 3307 行                            │
│  CurrentWorkBoundary    — 当前工作边界裁决                    │
├─────────────────────────────────────────────────────────────┤
│                    运行时基础设施 (runtime)                    │
│  RuntimeCompiler       — 5642 行  Prompt 编译与上下文组装    │
│  RuntimeAssembly       — 1231 行  运行时装配                 │
│  SingleAgentRuntimeHost — 799 行  服务主机                   │
│  ToolBatchPlanner      — 工具批处理调度                      │
│  ToolPlan              — 工具可见性计划                      │
│  DynamicContext        — 动态上下文管理                      │
│  Projection            — 运行时投影                          │
├─────────────────────────────────────────────────────────────┤
│                     核心循环 (loop)                          │
│  SingleAgentTurn       — 5114 行  单轮主循环                 │
│  TaskExecutor          — 8567 行  持续任务执行器             │
│  Admission             — 426 行   动作准入裁决               │
│  ActionPermit          — 247 行   动作许可                   │
│  ModelActionProtocol   — 585 行   模型动作协议               │
│  TaskLifecycle         — 任务生命周期                        │
│  ActiveWork            — 当前工作控制                        │
│  WorkRollout           — 工作展开                            │
│  TaskSteering          — 任务转向                            │
│  TaskToolApproval      — 工具审批                            │
├─────────────────────────────────────────────────────────────┤
│                     会话恢复 (continuation)                  │
│  Record                — 133 行   恢复记录                   │
│  RecoveryBoundary      — 261 行   恢复边界裁决               │
│  Selector              — 238 行   会话恢复选择               │
│  RecoveryPacket        — 恢复包                              │
├─────────────────────────────────────────────────────────────┤
│                     图任务引擎 (graph)                       │
│  Loop                  — 181K 行  图循环                     │
│  WorkOrderExecutor     — 90K 行   工作单执行                 │
│  ContextMaterializer   — 123K 行  上下文物化                 │
│  StateMachine          — 状态机                              │
│  TransitionProcessor   — 转换处理器                          │
└─────────────────────────────────────────────────────────────┘
```

---

## 二、核心数据流

### 2.1 单轮交互流程 (`single_agent_turn.py`)

```
用户请求 → HarnessRuntimeFacade.astream()
  │
  ├─ 1. 会话历史加载与自动压缩
  │     auto_compact_session_if_needed()
  │     assemble_runtime_history()
  │
  ├─ 2. 当前工作边界裁决
  │     decide_current_work_boundary()
  │     → CurrentWorkBoundaryReceipt
  │
  ├─ 3. 运行时装配
  │     assemble_runtime()
  │     → RuntimeAssembly (含 profile、工具、能力、环境)
  │
  ├─ 4. 运行时分支选择
  │     _runtime_branch_projection()
  │     → single_agent_turn / explicit_contract_task / blocked_runtime
  │
  ├─ 5. 编译阶段 (RuntimeCompiler)
  │     compiler.compile_single_agent_turn_packet()
  │     → RuntimeInvocationPacket
  │        ├─ model_messages: 组装后的模型消息
  │        ├─ available_tools: 可见工具列表
  │        ├─ allowed_action_types: 允许动作类型
  │        ├─ segment_plan: Prompt 分段计划
  │        └─ diagnostics: 编译诊断
  │
  ├─ 6. 工具可见性计划
  │     build_runtime_tool_plan()
  │     → RuntimeToolPlan (model_visible_tools, dispatchable_tool_names)
  │
  ├─ 7. 模型推理 (最多 8 轮工具迭代)
  │     call_model_invoker() → ModelActionRequest
  │     │
  │     ├─ 7a. 动作准入 (admission.py)
  │     │     admit_model_action()
  │     │     → AdmissionDecision (allow/deny/ask_approval/invalid/needs_contract/needs_task_run)
  │     │
  │     ├─ 7b. 动作许可 (action_permit.py)
  │     │     action_permit_from_admission()
  │     │     → ActionPermit (含 grant_scope、risk_fingerprint、approval_ref)
  │     │
  │     ├─ 7c. 工具批处理调度 (tool_batch_planner.py)
  │     │     build_tool_batch_plan()
  │     │     → ToolBatchPlan (按 concurrency_safe 分组)
  │     │
  │     ├─ 7d. 工具执行
  │     │     tool_control_plane.execute_batch()
  │     │     → ToolObservation 列表
  │     │
  │     └─ 7e. 观察吸收 → 回到 7 (最多 8 轮)
  │
  └─ 8. 收口
        respond / ask_user / block
        → final_answer_event / error_event
```

### 2.2 持续任务流程 (`task_executor.py`)

```
request_task_run → TaskLifecycleRecord
  │
  ├─ 1. 创建 TaskRunContract
  │     contract_from_action_request()
  │     → TaskRunContract (含 goal、criteria、resource_requirements)
  │
  ├─ 2. 启动任务生命周期
  │     start_task_lifecycle_from_action_request()
  │     → TaskLifecycleRecord
  │
  ├─ 3. 执行循环 (最多 12 步)
  │     execute_task_run()
  │     │
  │     ├─ 3a. 编译 (同单轮)
  │     ├─ 3b. 模型推理
  │     ├─ 3c. 动作准入
  │     ├─ 3d. 工具执行
  │     ├─ 3e. 控制信号检查
  │     │     pause_requested / stop_requested / replan_requested
  │     └─ 3f. 步骤状态记录
  │
  ├─ 4. 控制信号处理
  │     request_task_run_pause()
  │     resume_paused_task_run()
  │     stop_task_run()
  │     append_user_work_instruction()
  │
  └─ 5. 收口
        finish_task_lifecycle()
        → 产出 artifact_refs、work_rollout
```

---

## 三、关键设计决策

### 3.1 动作协议 (`model_action_protocol.py`)

定义了 7 种模型动作类型：

| 动作类型 | 用途 | 可用阶段 |
|---------|------|---------|
| `respond` | 直接回复用户 | 单轮 + 任务 |
| `ask_user` | 询问用户 | 单轮 + 任务 |
| `tool_call` | 调用工具 | 单轮 + 任务 |
| `request_task_run` | 启动持续任务 | 单轮 |
| `active_work_control` | 控制当前工作 | 单轮 |
| `resume_recoverable_work` | 恢复可恢复工作 | 单轮 |
| `block` | 阻塞 | 单轮 + 任务 |

**协议约束**：
- 单轮使用 `ModelActionRequest`（单 tool_call）
- 任务执行使用 `TaskExecutionModelActionRequest`（支持多 tool_calls）
- 动作必须通过 `AdmissionDecision` 准入，然后生成 `ActionPermit` 才能执行
- 协议错误可修复：`_REPAIRABLE_SINGLE_AGENT_PROTOCOL_ERRORS` 定义了 5 种可修复错误

### 3.2 准入系统 (`admission.py`)

`AdmissionDecision` 有 6 种裁决值：

```python
AdmissionDecisionValue = Literal[
    "allow",           # 允许执行
    "deny",            # 拒绝
    "ask_approval",    # 需要审批
    "invalid",         # 无效请求
    "needs_contract",  # 需要任务合同
    "needs_task_run",  # 需要持续任务
]
```

**准入检查链**：
1. 动作类型是否在允许列表中
2. 工具是否在服务面中
3. 计划模式是否拦截副作用工具
4. 副作用工具是否要求任务合同
5. 任务作用域工具是否要求持续任务
6. 重复失败守卫

### 3.3 工具批处理调度 (`tool_batch_planner.py`)

核心数据结构：

```
ToolConcurrencyDescriptor
  ├─ tool_name / operation_id
  ├─ read_only / destructive / concurrency_safe
  ├─ resource_locks: ToolResourceLock[]
  └─ execution_class: "exclusive" / "shared"

ToolBatchPlan
  ├─ items: ToolBatchItem[]
  └─ groups: ToolBatchGroup[]
       ├─ parallel: bool
       ├─ execution_class
       └─ resource_locks
```

**调度策略**：
- 按 `concurrency_safe` 标记分组
- 共享写目标、命令依赖、审批风险的工具串行执行
- 互不依赖的只读工具可以并行
- 超时控制：单轮 45 秒，任务 45 秒
- 最多 8 轮工具迭代（可配置，最大 32）

### 3.4 运行时装配 (`assembly.py`)

`RuntimeAssemblyProfile` 定义了完整的运行时策略：

```python
RuntimeAssemblyProfile:
  ├─ interaction_policy: 交互策略
  ├─ planning_policy: 计划策略 (plan_mode / todo_required)
  ├─ task_lifecycle_policy: 任务生命周期策略
  ├─ tool_exposure_policy: 工具暴露策略
  ├─ context_policy: 上下文策略
  ├─ memory_policy: 记忆策略
  ├─ subagent_policy: 子 Agent 策略
  ├─ self_review_policy: 自审策略
  ├─ step_summary_policy: 步骤摘要策略
  ├─ approval_policy: 审批策略
  └─ artifact_policy: 产物策略
```

`RuntimeAssembly` 是每轮运行时的完整快照，包含：
- profile、model_selection、runtime_contract
- task_environment、permission_mode
- capability_directory、skill_runtime_views
- available_tools、control_capabilities
- operation_authorization

### 3.5 文件证据策略

**核心规则**：
1. 修改前必须具有目标区域的当前有效读窗证据
2. 已覆盖且未过期的 read_file 窗口可以复用
3. 编辑失败先重新确认路径或局部文本，不原样重试
4. 写入后优先验证，不默认重读

**证据注入机制**：
- `file_evidence_decisions` 决定哪些读窗需要注入
- `read_evidence_injection` 将精确读窗内容注入模型上下文
- `FileStateAuthorityStore` 维护文件状态权威存储

### 3.6 会话恢复 (`continuation/`)

`ContinuationRecord` 状态机：

```
none → recoverable → waiting_approval → paused → blocked → terminal_read_only
```

**恢复策略**：
- `same_run_resume`：自动恢复
- `ask_user_confirm`：需要用户确认
- `require_approval`：需要审批

**选择逻辑** (`selector.py`)：
1. 检查 session_id 和 active_work
2. 列出所有 `single_agent_task` 类型的 task_run
3. 按 updated_at 降序排序
4. 跳过 graph_controlled 的任务
5. 根据 work_state 和 recovery_state 决定恢复策略

### 3.7 运行时主机 (`single_agent_host.py`)

持有以下存储和服务：

| 组件 | 用途 |
|------|------|
| `RuntimeFactLedger` | 事实账本 |
| `RuntimeEventLog` | 事件日志 |
| `RuntimeRunRegistry` | 运行注册表 |
| `RuntimeExecutionStore` | 执行存储 |
| `FileStateAuthorityStore` | 文件状态权威存储 |
| `RuntimeStateIndex` | 状态索引 |
| `RuntimeObjectStore` | 运行时对象存储 |
| `RuntimeTraceService` | 追踪服务 |
| `RuntimeObservabilityKernel` | 可观测性内核 |
| `RuntimeToolControlPlane` | 工具控制面 |
| `RuntimeMonitorService` | 监控服务 |
| `LangGraphCheckpointStore` | 图检查点存储 |
| `ActiveTurnRegistry` | 活跃轮次注册表 |
| `RuntimeCacheManager` | 缓存管理器 |
| `PromptAccountingLedger` | Prompt 计费账本 |

### 3.8 运行时外观 (`runtime_facade.py`)

`HarnessRuntimeFacade` 是 API 入口适配器，职责明确：

1. **接收 API 输入**：`astream(request: HarnessRuntimeRequest)`
2. **会话管理**：加载历史、自动压缩、上下文恢复
3. **运行时装配**：调用 `assemble_runtime()` 构建运行时快照
4. **分支选择**：根据运行时状态选择 `single_agent_turn` / `explicit_contract_task` / `blocked_runtime`
5. **事件流输出**：yield 事件给 API 层

**核心方法链**：
```
astream()
  ├─ auto_compact_session_if_needed()
  ├─ assemble_runtime_history()
  ├─ _commit_user_message()
  ├─ active_turn_registry.start()
  ├─ assemble_runtime()
  ├─ select_session_continuation()
  ├─ build_turn_input_facts()
  ├─ _decide_current_work_boundary_for_turn()
  ├─ _runtime_memory_context_for_turn()
  └─ _run_single_agent_turn() / _run_explicit_contract_task_turn()
```

### 3.9 图任务引擎 (`graph/`)

图引擎是旧架构，与新单 Agent 运行时并存：

**核心组件**：
- `GraphLoop`：图循环，驱动节点执行
- `GraphStateMachine`：状态机，管理图状态转换
- `GraphTransitionProcessor`：转换处理器，处理边条件
- `GraphContextMaterializer`：上下文物化器
- `WorkOrderExecutor`：工作单执行器

**节点执行**：
1. `GraphLoop.start()` → 创建初始工作单
2. `GraphLoop.advance()` → 执行当前节点
3. 节点结果通过 `NodeResultEnvelope` 返回
4. `TransitionProcessor` 评估边条件，决定下一个节点
5. 支持 revision 边类型（修订循环）

**与新架构的关系**：
- 图节点通过 `_graph_node_contract_from_work_order()` 转换为 `TaskRunContract`
- 图节点任务使用 `runtime.pack.graph_node_execution` prompt pack
- `graph_controlled` 标记的任务不会被会话恢复选择器选中

---

## 四、安全与边界

### 4.1 权限模型

- `permission_mode`：`full_access` / `restricted` / `plan_only`
- `operation_authorization`：按 operation_id 授权
- `approval_policy`：高风险操作需要审批
- `side_effect_policy`：副作用工具要求任务合同

### 4.2 计划模式

- `plan_mode_active`：限制副作用工具
- `plan_required`：要求先写计划
- `todo_required_when_task_run`：任务执行要求 todo

### 4.3 工具审批

- `task_tool_approval.py`：管理工具调用审批
- `approval_state_for_task_run()`：检查审批状态
- `matching_approval_grant_for_pending()`：匹配审批授权
- 审批通过后任务继续执行

### 4.4 失败守卫

| 守卫 | 阈值 | 行为 |
|------|------|------|
| 重复准入拒绝 | 2 次 | 暂停任务 |
| 重复准入拒绝 | 3 次 | 强制暂停 |
| 连续工具失败 | 3 次 | 记录观察 |
| 连续工具失败 | 4 次 | 阻塞任务 |
| 单轮工具迭代 | 8 次 (默认) | 强制收口 |
| 任务执行步骤 | 12 步 | 任务结束 |

---

## 五、规模统计

| 模块 | 目录 | 关键文件 | 行数 |
|------|------|---------|------|
| API 入口 | `entrypoint/` | `runtime_facade.py` (3307), `current_work_boundary.py` | ~170K |
| 运行时 | `runtime/` | `compiler.py` (5642), `assembly.py` (1231), `single_agent_host.py` (799) | ~700K |
| 核心循环 | `loop/` | `task_executor.py` (8567), `single_agent_turn.py` (5114), `admission.py` (426) | ~850K |
| 会话恢复 | `continuation/` | `record.py` (133), `selector.py` (238), `recovery_boundary.py` (261) | ~30K |
| 图引擎 | `graph/` | `loop.py`, `work_order_executor.py`, `context_materializer.py` | ~750K |
| Agent 控制 | `agent_control/` | | ~30K |
| 顶层 | `harness/` | | ~65K |
| **总计** | | | **~2.6M** |

---

## 六、架构特点总结

1. **协议驱动**：模型输出必须符合 `ModelActionRequest` 协议，通过准入才能执行
2. **分层清晰**：entrypoint → runtime → loop → continuation，每层职责明确
3. **安全边界**：工具按 operation_id 授权，计划模式限制副作用，审批流程保护高风险操作
4. **可恢复**：ContinuationRecord 支持会话中断后恢复，支持 same_run_resume / ask_user_confirm / require_approval
5. **可观测**：RuntimeEventLog + RuntimeTraceService + RuntimeObservabilityKernel 提供完整追踪
6. **批处理优化**：工具按并发安全分组执行，减少模型往返
7. **双引擎并存**：新单 Agent 运行时与旧图引擎并行，图节点可转换为单 Agent 任务
8. **文件证据策略**：修改前必须具有当前有效读窗证据，防止基于过期内容修改
9. **失败守卫**：多层守卫防止无限重试、重复失败和预算耗尽
10. **运行时装配**：每轮运行时快照包含完整策略、工具、能力和环境配置
