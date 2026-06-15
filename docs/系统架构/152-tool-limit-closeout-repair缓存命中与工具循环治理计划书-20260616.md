# tool-limit-closeout / repair 缓存命中与工具循环治理计划书

日期：2026-06-16  
状态：待用户审阅，未实施  
范围：单 Agent 工具循环、tool-limit-closeout、protocol/admission repair、mid-turn context compaction、工具结果投影与 prompt cache 稳定性  
不在范围：模型供应商替换、前端 UI 重构、任务图语义重写、权限系统整体重做、仅通过提高工具迭代上限规避问题

## 1. 目的

本计划用于修复最新会话中 `tool-limit-closeout` / `repair` 阶段缓存命中率明显低于正常工具 follow-up 的问题。

这不是要删除 `tool-limit-closeout` 或 `repair`。成熟 agent 都需要这两个安全机制：

- `tool-limit-closeout`：当单轮工具循环无法继续安全推进时，强制模型收口、询问用户或明确阻塞。
- `repair`：当模型输出不符合运行协议时，给模型一次受控修正机会，避免协议错误直接污染执行层。

真正需要修复的是：它们不能成为常见压力释放路径。成熟做法是先通过工具结果预算、上下文压缩、稳定 cache prefix、history 规范化和失败边界收束，让 closeout / repair 只在极限情况下触发。

本计划的目标同时升级为成熟 agent 级缓存与性能目标：在 warmed follow-up 中，输入侧稳定前缀应尽量命中，miss 应严格限制在本轮新增尾部；输出 token 本身不属于 prompt cache 命中对象，不应把“输出未命中”误判为输入缓存失败。任何修复都必须以真实性能提升为前提，不能用额外模型调用、频繁重压缩或扩大本地 CPU/IO 开销换取表面命中率。

## 2. 当前症状与系统性问题

### 2.1 最新会话症状

已追查的最新会话：

- Session：`session-f92916b8c8004566`
- 最新 run：`turnrun:strun:d0219915d5514f12b3f87801b374527c`
- prompt cache 记录：`13` 条，状态均为 `hit`
- prompt tokens：约 `1,380,874`
- cached tokens：约 `1,102,464`
- 整体命中率：约 `79.84%`
- 末端 `tool-limit-closeout / repair` 阶段：约 `56%` 到 `59%`

结论：provider cache 不是失效，而是末端 closeout / repair 链路的 volatile 内容、控制消息、工具轨迹和修复提示把可复用 prefix 往后挤，导致缓存复用比例下降。

### 2.2 成熟 Agent 级缓存目标

用户补充确认：Codex 和 Claude Code 在大多数 warmed 场景下，表现接近“只有输出是未命中的”。本项目应把这个作为目标，但必须精确定义。

准确含义：

- 输出 token 是本轮新生成内容，本来不属于 prompt cache 可命中范围。
- 输入 prompt 的稳定 prefix 应保持 byte-stable，并被 provider cache 复用。
- 输入 miss 应主要来自本轮新增尾部，包括当前用户消息、最新工具 observation、少量 runtime control signal、必要 repair error preview。
- closeout / repair 不能把完整工具轨迹、完整 history、完整动态状态重新推到 prompt 前部。

目标状态：

```text

warmed normal follow-up:
  global/static/session/task stable prefix -> cache hit
  current user/latest tool observation/control suffix -> allowed miss
  completion/output tokens -> newly generated, not counted as prompt cache failure

warmed closeout/repair:
  stable prefix -> cache hit
  closeout/repair control payload -> bounded volatile suffix
  no full tool trajectory replay
  no unplanned model call

```

不能承诺字面 100% 输入命中，因为 provider cache TTL、模型配置变化、工具目录变化、项目指令变化、上下文窗口策略切换都会导致合理 miss。但验收目标必须是：在没有这些合理变化时，输入侧 miss 被限制在当前 turn 的最小 volatile suffix，而不是稳定段反复失效。

### 2.3 深层系统问题

当前问题不是单个阈值太小，而是工具循环压力治理的权责顺序不够成熟。

当前主链路集中在：

- `D:\AI应用\langchain-agent\backend\harness\loop\single_agent_turn.py`

该文件同时处理：

- 工具循环执行
- 协议解析
- 协议 repair
- admission repair
- tool-limit closeout
- agent-authored closeout
- deterministic closeout
- consecutive failure closeout
- mid-turn context compaction
- follow-up packet 重编译

这造成一个结构性风险：`single_agent_turn.py` 在同一个大循环里既观察压力、又决定是否压缩、又决定是否 repair、又决定是否 closeout，导致 closeout / repair 容易从安全护栏变成常见出口。

正确目标不是提高 `_MAX_SINGLE_TURN_TOOL_ITERATIONS`，而是把压力处理前移，让工具循环在接近硬限制前先经过明确的 Context Pressure Boundary。

## 3. 来源依据

### 3.1 本地项目依据

本项目已经具备一部分成熟组件，问题不是完全缺失机制，而是触发顺序和权威归属还没有收束。

| 文件 | 当前事实 | 设计含义 |
| --- | --- | --- |
| `D:\AI应用\langchain-agent\backend\harness\loop\single_agent_turn.py:75` | 定义单轮工具迭代上限、protocol recovery 上限 | 硬限制存在，但不应成为主压力治理策略 |
| `D:\AI应用\langchain-agent\backend\harness\loop\single_agent_turn.py:207` | 构造 tool-limit closeout control signal | closeout 是受控安全出口，应保留 |
| `D:\AI应用\langchain-agent\backend\harness\loop\single_agent_turn.py:745` | agent-authored closeout 已能带 segment plan | closeout 可以纳入 prompt accounting，不应存在未规划模型调用 |
| `D:\AI应用\langchain-agent\backend\harness\loop\single_agent_turn.py:899` | tool-limit closeout 内部还会触发 protocol repair | closeout 和 repair 嵌套会放大 volatile suffix |
| `D:\AI应用\langchain-agent\backend\harness\loop\single_agent_turn.py:1279` | 达到工具迭代上限后直接进入 tool-limit closeout | 缺少硬限制前的统一压力裁决层 |
| `D:\AI应用\langchain-agent\backend\harness\loop\single_agent_turn.py:1591` | 已存在 mid-turn context compaction 调用点 | 机制存在，但需要升级为 closeout 前必经 gate |
| `D:\AI应用\langchain-agent\backend\harness\runtime\compiler.py:600` | single-agent turn 已分 stable prefix 与 volatile suffix | prompt 分层基础已存在，应继续利用 |
| `D:\AI应用\langchain-agent\backend\harness\runtime\compiler.py:1181` | task execution packet 已有 stable / volatile 分段 | 不应再绕过 RuntimeCompiler / segment_plan |
| `D:\AI应用\langchain-agent\backend\harness\runtime\context_budget_policy.py:200` | 已计算 tool trajectory、preview、protocol history 等预算 | 应把预算接入 closeout 前压力治理 |
| `D:\AI应用\langchain-agent\backend\harness\runtime\dynamic_context\tool_result_projector.py:20` | 已有工具结果投影、preview、rehydration plan | 应冻结替换决策，避免跨 follow-up 改写 prompt |
| `D:\AI应用\langchain-agent\backend\harness\runtime\dynamic_context\replacement_store.py:13` | replacement record 有 content hash 与 policy hash | 可扩展为稳定 replacement decision 的依据 |
| `D:\AI应用\langchain-agent\backend\context_system\compaction\microcompact.py:27` | 已能根据 cache temperature 判断是否允许本地 rewrite | 可作为 cache-safe microcompact 策略入口 |
| `D:\AI应用\langchain-agent\backend\context_system\compaction\hooks.py:13` | 已有 pre-compact request 与 compact receipt | 可升级为 closeout 前压力边界凭证 |
| `D:\AI应用\langchain-agent\backend\context_system\compaction\invariants.py:29` | 已检查 current user 与 tool call/result 配对 | repair/compact 后必须复用这些不变量 |

### 3.2 本地文档依据

- `D:\AI应用\langchain-agent\docs\系统架构\149-prompt-cache低命中追查记录-20260615.md`
  - 已修复 early stable prefix 被动态内容切裂的问题。
  - 明确要求所有主链路 model call 必须有 `segment_plan` 和 `cache_metric_scope`。
  - 该计划的剩余问题是工具循环末端 closeout / repair 阶段缓存掉点。

- `D:\AI应用\langchain-agent\docs\系统架构\151-ContinuationRecord断线恢复权威重构设计书-20260615.md`
  - 明确了成熟 agent 的 authority chain：事实、模型决策、授权、执行、恢复必须分层。
  - 本计划沿用同一原则：压缩、repair、closeout 也必须有边界，不应让执行循环临时重判。

### 3.3 Codex 参考依据

Codex 的核心做法是：硬 closeout 不是正常压力释放路径，正常路径是采样前和工具循环中间的 token-aware compact。

关键源码：

- `D:\AI应用\openai-codex\codex-rs\core\src\session\turn.rs:147`
  - 采样前调用 `run_pre_sampling_compact`。
- `D:\AI应用\openai-codex\codex-rs\core\src\session\turn.rs:265`
  - 工具 follow-up 后计算 `auto_compact_token_status`。
- `D:\AI应用\openai-codex\codex-rs\core\src\session\turn.rs:290`
  - token limit reached 且还需要 follow-up 时，先 `run_auto_compact`，再继续。
- `D:\AI应用\openai-codex\codex-rs\core\src\session\turn.rs:659`
  - token status 区分 active context、compact scope 与 full context window。
- `D:\AI应用\openai-codex\codex-rs\core\src\context_manager\history.rs:366`
  - `normalize_history` 规范化 tool call / output 配对。
- `D:\AI应用\openai-codex\codex-rs\core\src\context_manager\history.rs:462`
  - `truncate_function_output_payload` 在 history 回灌前截断工具输出。
- `D:\AI应用\openai-codex\codex-rs\core\src\tools\context.rs:308`
  - `ExecCommandToolOutput` 记录 `original_token_count`、`max_output_tokens`、truncated output。

可借鉴不变量：

1. 先压缩，再继续采样。
2. 工具输出进入模型前先预算化。
3. 历史必须保持 tool call / tool result 配对。
4. 硬限制只作为最终边界。

### 3.4 Claude Code 参考依据

Claude Code 的核心做法是：每次 API 调用前都先稳定工具结果预算和上下文压缩，同时非常重视 prompt cache byte-stability。

关键源码：

- `D:\AI应用\claude-code-nb-main\query.ts:241`
  - 主 `queryLoop`。
- `D:\AI应用\claude-code-nb-main\query.ts:379`
  - API 调用前先 `applyToolResultBudget`。
- `D:\AI应用\claude-code-nb-main\query.ts:412`
  - autocompact 前先 microcompact。
- `D:\AI应用\claude-code-nb-main\query.ts:1506`
  - `maxTurns` 是 continuation 处的硬边界，不是主治理策略。
- `D:\AI应用\claude-code-nb-main\utils\toolResultStorage.ts:374`
  - replacement state 必须稳定以保护 prompt cache。
- `D:\AI应用\claude-code-nb-main\utils\toolResultStorage.ts:924`
  - `applyToolResultBudget` 统一处理工具结果预算。
- `D:\AI应用\claude-code-nb-main\services\compact\microCompact.ts:296`
  - cached microcompact 使用 cache editing，不改本地 message 内容。
- `D:\AI应用\claude-code-nb-main\services\compact\autoCompact.ts:241`
  - `autoCompactIfNeeded` 是 API 调用前的常规治理步骤。
- `D:\AI应用\claude-code-nb-main\services\api\claude.ts:3078`
  - 每次请求只保留一个 message-level cache control marker。
- `D:\AI应用\claude-code-nb-main\services\api\claude.ts:3164`
  - 给 cached prefix 内的 tool_result 添加 `cache_reference`，不直接改原始消息。

可借鉴不变量：

1. 工具结果的替换/保留决策一旦做出，后续调用必须稳定复用。
2. cache warm 时不能随意本地改写已缓存前缀。
3. max turns 是硬边界，不是主要上下文治理方式。
4. repair / recovery 必须有限次、有 circuit breaker，并保持协议形状。

## 4. 取舍分析

### 4.1 不采用的方案：直接提高工具迭代上限

不建议把 `_MAX_SINGLE_TURN_TOOL_ITERATIONS` 从当前上限继续提高作为主修复。

原因：

- 工具轨迹会继续增长，volatile suffix 更长。
- repair/closeout 更晚触发，但触发时 prompt 更大，缓存命中可能更差。
- 会掩盖重复工具调用、上下文预算和工具结果投影的问题。
- 与 Codex / Claude Code 的成熟方向相反。

保留迭代上限，但把它降级为最后安全边界。

### 4.2 不采用的方案：删除 repair 或 closeout

不能删除。

原因：

- 模型输出协议错误时必须有受控修正机会。
- 工具循环失控时必须能安全收口。
- 没有 closeout 会让 runtime 在无限工具循环、重复失败、无效输出中耗尽资源。

正确做法是降低触发率，并约束触发后的 prompt 形态。

### 4.3 采用的方案：Context Pressure Boundary + Stable Tool Result Budget + Recovery/Closeout 权责收束

本计划采用三层治理：

```text

工具结果预算
-> context pressure boundary
-> repair / closeout boundary

```

含义：

1. 工具结果先预算化、投影化、可 rehydrate。
2. 每次 follow-up 前根据 context usage 和 cache 状态决定是否 compact。
3. 达到硬迭代上限前，必须先尝试 cache-safe compact / packet recompile。
4. repair 只修复协议，不重新决定任务目标。
5. closeout 只收口，不再请求工具，不嵌套产生新的决策权威。

### 4.4 性能优先取舍

本计划不接受“为了缓存命中率牺牲真实运行性能”的修复。缓存治理必须同时改善或至少不损害以下指标：

- 模型调用次数：正常 follow-up 不能因为新增边界而增加额外模型调用。
- 端到端延迟：普通短 turn 和正常工具 follow-up 的 p50 / p95 latency 不能回退。
- 本地 CPU：pressure snapshot、hash、projection 只能处理当前 packet、最新 observation 和已有 ledger 索引，不能每轮全量扫描历史 runtime_state。
- 本地 IO：replacement / budget decision 必须 content-addressed 复用，不能反复写入等价 replacement 文件。
- prompt tokens：closeout / repair 的输入 tokens 必须下降或保持 bounded，不能为了结构化而拼接更多上下文。
- compact 成本：不能每轮无条件 compact；只有预测收益大于成本、接近压力阈值或 provider 报错时才 compact。
- 用户体验：压缩、repair、closeout 不能阻断实时流式反馈；只能在模型调用之间或工具批次边界执行。

性能上的核心取舍：

```text

默认路径:
  cheap snapshot + frozen budget lookup + normal follow-up

压力路径:
  compact only when threshold/gain/circuit-breaker allow

失败路径:
  minimal repair payload -> bounded closeout -> deterministic fallback

禁止路径:
  every-call compaction
  full-history reserialization
  extra model call just to improve metrics
  repeated replacement writes for same content

```

如果某个实现让缓存命中率上升，但增加模型调用次数、明显增加延迟、扩大 prompt tokens 或增加重复 IO，该实现不能通过验收。

## 5. 目标权威链

目标链路：

```text

ToolObservationEnvelope
-> ToolResultBudgetDecision
-> HistoryProtocolNormalizer
-> ContextPressureSnapshot
-> ContextPressureBoundaryDecision
-> RuntimeStartPacket / FollowupPacket
-> ModelTurnDecision
-> ProtocolRecoveryBoundary
-> CloseoutBoundary
-> PromptAccountingRecord

```

权责表：

| 层 | 允许做什么 | 禁止做什么 |
| --- | --- | --- |
| ToolObservationEnvelope | 记录工具输出、状态、文件事实、idempotency key | 不能决定后续是否 closeout |
| ToolResultBudgetDecision | 决定 preview、replacement、rehydration ref，冻结本轮替换策略 | 不能修改用户目标，不能改写稳定 prefix |
| HistoryProtocolNormalizer | 保证 tool call / tool result 配对，移除 orphan 或生成协议安全占位 | 不能替模型选择下一动作 |
| ContextPressureSnapshot | 观察 token、cache hit、iteration、tool trajectory、repair count | 不能执行 compact |
| ContextPressureBoundaryDecision | 决定 continue / compact_first / closeout_required / ask_user_required | 不能直接生成最终回答 |
| RuntimeStartPacket / FollowupPacket | 用 RuntimeCompiler 组装 stable/volatile segment_plan | 不能绕过 segment_plan 发模型调用 |
| ModelTurnDecision | 选择 respond / ask_user / tool_calls / block | 不能授权自身越过工具边界 |
| ProtocolRecoveryBoundary | 对协议错误做有限 repair | 不能重写任务目标或打开工具权限 |
| CloseoutBoundary | 统一 tool-limit、连续失败、协议耗尽后的收口 | 不能请求工具，不能无限 repair |
| PromptAccountingRecord | 记录 source、scope、segment_plan、cache hit/miss | 不能影响执行决策 |

## 6. 固定执行流

目标执行流：

```text

1. single_agent_turn 接收 initial packet。
2. 模型输出 action_request。
3. 解析协议。
4. 若协议错误：
   4.1 ProtocolRecoveryBoundary 检查剩余 repair 次数。
   4.2 构造最小 volatile repair payload。
   4.3 repair 失败或超限后进入 CloseoutBoundary。
5. 若模型请求工具：
   5.1 ActionPermit / admission 校验。
   5.2 执行工具。
   5.3 ToolObservationEnvelope 记录工具输出。
   5.4 ToolResultBudgetDecision 预算化工具结果。
   5.5 HistoryProtocolNormalizer 规范化协议历史。
   5.6 ContextPressureSnapshot 读取 token/cache/iteration 状态。
   5.7 ContextPressureBoundary 裁决：
       - continue：正常编译 follow-up packet。
       - compact_first：执行 compact，验证 invariant，通过后重编 follow-up packet。
       - closeout_required：进入 CloseoutBoundary。
       - ask_user_required：模型收口询问，不再调用工具。
6. 若 tool_iteration 接近硬上限：
   6.1 不能直接 closeout。
   6.2 必须先经过 ContextPressureBoundary。
   6.3 只有 compact 不可用、已失败、收益不足或协议状态不安全时，才 closeout。
7. closeout model call 必须使用 closeout segment_plan 和 cache_metric_scope。
8. closeout 输出若仍协议错误：
   8.1 只允许有限 closeout repair。
   8.2 超限后 deterministic closeout。
9. 所有模型调用写入 PromptAccountingRecord。

```

禁止执行流：

```text

tool_iteration >= max
-> 直接拼接大段 closeout prompt
-> repair 再拼接动态错误详情
-> 再进入 agent-authored closeout
-> 多次模型调用共享不了稳定 prefix

```

## 7. 数据与协议设计

### 7.1 ToolResultBudgetDecision

建议新增或沉淀为显式结构：

```text

decision_id: string
session_id: string
turn_id: string
task_run_id: string
tool_call_id: string
tool_name: string
source_result_hash: string
projection_policy_hash: string
decision: inline | preview_only | persisted_rehydration | file_window_ref
preview_chars: int
replacement_ref: string
rehydration_plan: dict
frozen: bool
reason: string
authority: harness.runtime.tool_result_budget_decision

```

规则：

- 同一个 `tool_call_id + source_result_hash + projection_policy_hash` 的决策必须稳定。
- 如果 replacement 已生成，后续 follow-up 复用相同 preview 和 ref。
- cache warm 且 provider 不支持 cache editing 时，不允许改写已缓存的历史内容。
- read_file 的 line window 继续按文件证据策略处理，不混入普通大文本持久化。

### 7.2 ContextPressureSnapshot

建议字段：

```text

snapshot_id: string
session_id: string
turn_id: string
task_run_id: string
tool_iteration: int
max_tool_iterations: int
protocol_recovery_attempts: int
provider_prompt_tokens: int
provider_cached_tokens: int
local_estimated_tokens: int
cache_hit_rate: float
volatile_chars: int
tool_trajectory_count: int
latest_observation_count: int
active_failure_count: int
auto_replacement_allowed: bool
pressure_level: normal | warm_pressure | high | critical
authority: harness.loop.context_pressure_snapshot

```

来源：

- `ContextUsageMeter`
- `prompt_accounting` latest record
- `context_budget_policy`
- 当前 `tool_iteration`
- 当前 repair attempts

### 7.3 ContextPressureBoundaryDecision

建议裁决：

```text

continue
compact_first
closeout_required
ask_user_required
blocked_protocol_unsafe

```

必要字段：

```text

decision_id
snapshot_id
action
reason
required_receipt_ref
allowed_next_packet_kind
blocked_reason
diagnostics
authority = harness.loop.context_pressure_boundary

```

规则：

- `tool_iteration >= max - 1` 且仍需 follow-up 时，优先 `compact_first`。
- compact 已失败连续达到阈值时，`closeout_required`。
- protocol 状态不安全时，不能 compact 后继续工具，应进入 repair 或 closeout。
- compact 成功后必须重编 follow-up packet，并验证 stable prefix 未被动态内容提前切裂。

### 7.4 ProtocolRecoveryBoundary

目标不是重写 repair 文案，而是收束 repair 权威。

规则：

- repair 只接收：
  - 原始模型响应的短 preview
  - 结构化 protocol error code
  - 当前允许 action schema
  - 当前 phase
  - remaining attempts
- repair 不接收完整工具轨迹。
- repair 不允许开放工具调用。
- repair 的 model call 必须有 segment_plan。
- repair 超过上限后进入 CloseoutBoundary，不再嵌套更多 repair。

### 7.5 CloseoutBoundary

统一以下 closeout 来源：

- tool iteration limit
- consecutive tool failures
- protocol recovery exhausted
- admission repair exhausted
- unsafe closeout content
- model empty response

CloseoutBoundary 只做一件事：生成受控的用户可见收口。

允许输出：

- `respond`
- `ask_user`
- `block`

禁止输出：

- tool calls
- request_task_run
- continue hidden loop
- 修改任务目标
- 编造已经完成的验证结果

## 8. 模块计划

### 8.1 新增 `backend/harness/loop/context_pressure_boundary.py`

职责：

- 从现有 meter、prompt accounting、iteration、repair attempt 构造 `ContextPressureSnapshot`。
- 裁决 `continue / compact_first / closeout_required / ask_user_required`。
- 输出 `ContextPressureBoundaryDecision`。

不做：

- 不执行 compact。
- 不调用模型。
- 不解析模型 action。

### 8.2 新增或收束 `backend/harness/loop/protocol_recovery_boundary.py`

职责：

- 管理 protocol repair 和 admission repair 的次数、phase、payload 最小化。
- 生成 repair segment_plan 所需的 message specs。
- repair exhausted 后产出 closeout reason。

不做：

- 不执行工具。
- 不改变用户目标。
- 不把 repair 当作新一轮任务规划。

### 8.3 新增或收束 `backend/harness/loop/closeout_boundary.py`

职责：

- 统一 tool-limit closeout、agent-authored closeout、deterministic closeout 的入口和状态。
- 保证 closeout model call 必须带 `segment_plan`、`cache_metric_scope`、`source`。
- closeout 输出不合规时统一 deterministic fallback。

不做：

- 不允许 closeout 期间再次请求工具。
- 不生成新的 task request。

### 8.4 扩展 `backend/harness/runtime/dynamic_context/replacement_store.py`

职责：

- 支持按 `source_result_hash + projection_policy_hash` 查询已冻结 replacement decision。
- 保存 `frozen=true` 的预算决策。
- resume / follow-up 时可复用同一 decision。

注意：

- 不把 runtime private path 暴露给普通工具。
- 继续通过 rehydration ref 和专用读取工具恢复省略内容。

### 8.5 扩展 `backend/harness/runtime/dynamic_context/tool_result_projector.py`

职责：

- 在生成 projection 时消费或产出 `ToolResultBudgetDecision`。
- 对大输出保持 preview/ref 稳定。
- 输出 budget diagnostics 给 prompt accounting。

### 8.6 调整 `backend/harness/loop/single_agent_turn.py`

目标是减少该文件的决策权，而不是在里面继续堆分支。

保留：

- 主 async generator。
- 事件流 yield。
- 调用工具执行器。
- 调用新增 boundary 模块。

迁出：

- pressure 裁决。
- protocol repair payload 组装。
- closeout payload 组装。
- deterministic closeout 策略。

### 8.7 调整 `backend/harness/runtime/compiler.py`

目标：

- follow-up packet 必须在 compact / budget decision 后重编。
- closeout / repair / follow-up 的 `segment_plan` 全部进入 accounting。
- dynamic segments 必须携带 volatility metadata。

不建议：

- 不重写整个 compiler。
- 不引入另一套 prompt renderer。

### 8.8 调整测试

新增或更新：

- `backend/tests/single_agent_turn_pressure_boundary_test.py`
- `backend/tests/tool_result_budget_decision_regression.py`
- `backend/tests/protocol_recovery_boundary_regression.py`
- `backend/tests/closeout_boundary_regression.py`
- `backend/tests/prompt_accounting_ledger_test.py`
- `backend/tests/dynamic_prompt_context_projection_test.py`
- `backend/tests/tool_result_projection_regression.py`

删除或改写：

- 保护旧 closeout 内部分支形状的测试。
- 只断言旧函数存在、不保护用户可见行为的测试。
- 为旧兼容路径保留的语义测试。

## 9. 分阶段实施计划

### Phase 0：基线确认与样本固化

目标：先锁定当前症状，避免修复后无法判断是否真的改善。

动作：

- 读取最新 session 的 prompt accounting records。
- 记录每个 model call 的：
  - source
  - invocation_kind
  - segment_plan_ref
  - prompt_tokens
  - cached_tokens
  - input_miss_tokens
  - completion_tokens
  - cache hit rate
  - tool_iteration
  - repair phase
  - model_call_latency_ms
  - prompt_assembly_latency_ms
  - compaction_latency_ms
  - tool_result_projection_latency_ms
- 固化一个低命中样本报告。

涉及文件：

- `D:\AI应用\langchain-agent\backend\runtime\prompt_accounting\ledger.py`
- `D:\AI应用\langchain-agent\backend\runtime\prompt_accounting\stability_report.py`
- `D:\AI应用\langchain-agent\backend\scripts\diagnose_deepseek_prompt_cache.py`

完成标准：

- 能复现 closeout / repair 阶段命中率低于正常 follow-up。
- 能确认 `unplanned_model_call` 为 `0` 或列出剩余来源。
- 能区分 prompt input miss 与 completion/output tokens。
- 能记录修复前普通 follow-up、repair、closeout 的 p50 / p95 latency 基线。
- 不修改 runtime 行为。

禁止：

- 禁止通过删账本、筛掉低命中记录来制造改善。

### Phase 1：ContextPressureBoundary shadow

目标：先新增观察与裁决对象，但不改变执行路径。

动作：

- 新增 `ContextPressureSnapshot`。
- 新增 `ContextPressureBoundaryDecision`。
- 在现有 mid-turn compaction 附近 shadow 计算 decision。
- 只写 diagnostics，不改变 continue / closeout 行为。

涉及文件：

- 新增 `D:\AI应用\langchain-agent\backend\harness\loop\context_pressure_boundary.py`
- 修改 `D:\AI应用\langchain-agent\backend\harness\loop\single_agent_turn.py`
- 修改 `D:\AI应用\langchain-agent\backend\runtime\prompt_accounting\context_usage_meter.py`
- 新增 `D:\AI应用\langchain-agent\backend\tests\single_agent_turn_pressure_boundary_test.py`

完成标准：

- 每次工具 follow-up 前都有 pressure snapshot。
- 达到 `max - 1` 的工具迭代能产生 `compact_first` 或 `closeout_required` shadow decision。
- shadow decision 与 prompt accounting 可关联。
- shadow 计算不得引入额外模型调用。
- shadow 计算必须使用已有 packet、meter、ledger 索引，不做全量历史扫描。

禁止：

- 禁止在该阶段改变 closeout 行为。
- 禁止直接提高工具迭代上限。

### Phase 2：工具结果预算决策冻结

目标：让工具结果 preview / replacement / rehydration 在同一 turn 和后续 follow-up 中稳定。

动作：

- 引入 `ToolResultBudgetDecision`。
- `tool_result_projector` 先查冻结决策，再生成新 projection。
- `replacement_store` 保存 decision 级别 metadata。
- 对 read_file、shell、大 JSON、错误结果分别建立预算规则。

涉及文件：

- `D:\AI应用\langchain-agent\backend\harness\runtime\dynamic_context\tool_result_projector.py`
- `D:\AI应用\langchain-agent\backend\harness\runtime\dynamic_context\replacement_store.py`
- `D:\AI应用\langchain-agent\backend\runtime\tool_runtime\tool_result_envelope.py`
- `D:\AI应用\langchain-agent\backend\harness\runtime\context_budget_policy.py`
- 新增 `D:\AI应用\langchain-agent\backend\tests\tool_result_budget_decision_regression.py`

完成标准：

- 同一个工具结果在多次 follow-up 中 projection hash 稳定。
- 大输出只进入 preview + rehydration ref。
- cache warm 时不会本地改写已缓存前缀。
- read_file 仍要求目标行新鲜证据，不允许从旧 preview 编辑。

禁止：

- 禁止把完整工具输出塞回 closeout / repair prompt。
- 禁止暴露 runtime private replacement 文件路径给普通模型工具。

### Phase 3：compact-first 接管硬上限前路径

目标：让 closeout 前先经过成熟的 context pressure gate。

动作：

- 当 `tool_iteration >= max - 1` 且模型仍需 follow-up 时，先请求 `ContextPressureBoundary`。
- 若 decision 为 `compact_first`：
  - 调用现有 `compact_session_context`。
  - 校验 compaction invariant。
  - 重新编译 follow-up packet。
  - 继续一轮模型 follow-up。
- 若 compact 不可用、失败、收益不足或协议不安全，再进入 closeout。

涉及文件：

- `D:\AI应用\langchain-agent\backend\harness\loop\single_agent_turn.py`
- `D:\AI应用\langchain-agent\backend\context_system\compaction\hooks.py`
- `D:\AI应用\langchain-agent\backend\context_system\compaction\invariants.py`
- `D:\AI应用\langchain-agent\backend\runtime\context_management\session_compaction.py`
- `D:\AI应用\langchain-agent\backend\harness\runtime\semantic_compaction_adapter.py`

完成标准：

- 工具硬上限前至少经过一次明确 pressure boundary。
- compact 成功后 follow-up packet 的 stable prefix 不被动态内容提前切裂。
- compact 失败有 receipt 和 reason，不静默继续膨胀。
- closeout 触发率下降，而不是只延后触发。
- compact 只在 pressure threshold、预测收益或 provider overflow 条件满足时触发。
- 普通 warmed follow-up 不因该阶段增加额外模型调用。

禁止：

- 禁止 compact 后不重编 packet。
- 禁止 compact invariant 失败后继续工具调用。

### Phase 4：ProtocolRecoveryBoundary 收束 repair

目标：repair 只修协议，不重判任务，不扩大上下文。

动作：

- 把 `_repair_single_agent_*` 相关 repair message 构造迁入 `protocol_recovery_boundary.py`。
- repair payload 最小化。
- repair model call 必须有 segment_plan。
- repair exhausted 后统一进入 CloseoutBoundary。
- closeout 内的 repair 不允许再嵌套进入普通 tool loop。

涉及文件：

- 新增 `D:\AI应用\langchain-agent\backend\harness\loop\protocol_recovery_boundary.py`
- 修改 `D:\AI应用\langchain-agent\backend\harness\loop\single_agent_turn.py`
- 修改 `D:\AI应用\langchain-agent\backend\harness\loop\admission.py`
- 修改 `D:\AI应用\langchain-agent\backend\prompt_composition\message_specs.py`
- 新增 `D:\AI应用\langchain-agent\backend\tests\protocol_recovery_boundary_regression.py`

完成标准：

- protocol repair 每次都有明确 phase、attempt、max_attempts。
- repair prompt 不携带完整工具轨迹。
- repair 失败不会产生新的工具调用。
- repair exhausted 后只有 closeout 或 deterministic failure。

禁止：

- 禁止 repair 替模型选择新的 task request。
- 禁止 repair 绕过 admission。

### Phase 5：CloseoutBoundary 统一收口

目标：把多处 closeout 分支收束为一条清晰出口。

动作：

- 新增 `closeout_boundary.py`。
- 统一 tool-limit、consecutive failures、protocol exhausted、empty response 的 closeout payload。
- closeout model call 的 `source`、`cache_metric_scope`、`segment_plan`、`segment_plan_ref` 必须完整。
- closeout 输出 schema 固定为 `respond / ask_user / block`。
- deterministic closeout 只在模型 closeout 不可用或不合规时触发。

涉及文件：

- 新增 `D:\AI应用\langchain-agent\backend\harness\loop\closeout_boundary.py`
- 修改 `D:\AI应用\langchain-agent\backend\harness\loop\single_agent_turn.py`
- 修改 `D:\AI应用\langchain-agent\backend\runtime\prompt_accounting\serializer.py`
- 修改 `D:\AI应用\langchain-agent\backend\runtime\prompt_accounting\stability_report.py`
- 新增 `D:\AI应用\langchain-agent\backend\tests\closeout_boundary_regression.py`

完成标准：

- closeout 期间没有工具调用。
- closeout model call 全部可在 prompt accounting 中追踪。
- closeout repair 超限后 deterministic closeout。
- tool-limit closeout 不再重复拼接大段动态 history。

禁止：

- 禁止保留多条互相竞争的 closeout 分支。
- 禁止为了兼容旧路径保留无 segment_plan 的模型调用。

### Phase 6：旧权威清理与 cutover

目标：删掉旧的分散决策，避免新旧双链路并存。

动作：

- 从 `single_agent_turn.py` 删除迁出的 payload 组装和策略分支。
- 删除只保护旧内部函数形状的测试。
- 搜索所有 closeout / repair 来源，确保只通过新 boundary。
- 更新架构文档和诊断脚本。

涉及文件：

- `D:\AI应用\langchain-agent\backend\harness\loop\single_agent_turn.py`
- `D:\AI应用\langchain-agent\backend\tests\harness_model_action_protocol_regression.py`
- `D:\AI应用\langchain-agent\backend\tests\prompt_accounting_ledger_test.py`
- `D:\AI应用\langchain-agent\backend\scripts\diagnose_deepseek_prompt_cache.py`

完成标准：

- `single_agent_turn.py` 不再拥有 pressure / repair / closeout 的策略权威，只负责 orchestration。
- `rg "tool_limit_closeout|protocol_recovery|agent_authored_closeout"` 能清晰指向 boundary 或调用点。
- 无旧兼容分支继续影响主路径。

禁止：

- 禁止把旧函数简单包一层 facade 后继续保留同等权威。

### Phase 7：真实运行验证

目标：证明修复不是静态通过，而是在真实 agent loop 中改善。

动作：

- 使用固定端口启动后端 `http://127.0.0.1:8003`。
- 使用固定端口启动前端 `http://127.0.0.1:3000`。
- 用同类长工具任务跑端到端样本。
- 对比修复前后 prompt accounting。

完成标准：

- `unplanned_model_call` 为 `0`。
- closeout / repair 触发率下降。
- closeout / repair 阶段 cache hit rate 不再比上一轮正常 follow-up 大幅断崖式下降。
- 工具循环在压力升高时优先出现 compact receipt，而不是直接 closeout。
- warmed follow-up 的输入 miss 主要集中在 current user、latest tool observation、runtime control suffix。
- completion/output tokens 单独统计，不作为 prompt cache miss。
- 同类任务的平均 prompt tokens、repair 模型调用次数、hard closeout 次数下降。
- 普通短 turn 和正常 follow-up 的 p50 / p95 latency 不回退；若有波动，必须由 token 减少或 provider 延迟变化解释。
- 前后端固定端口真实可用。

禁止：

- 禁止只用静态检查宣布成功。
- 禁止跳过失败测试或降低断言。

## 10. 文件级 checklist

| 文件 | 当前角色 | 目标动作 | 完成条件 |
| --- | --- | --- | --- |
| `backend/harness/loop/single_agent_turn.py` | 主工具循环与多种策略混合 | 迁出 pressure / repair / closeout 策略权威 | 文件只保留 orchestrator 调用与事件流 |
| `backend/harness/loop/context_pressure_boundary.py` | 不存在 | 新增上下文压力边界 | 每轮 follow-up 前能产出 decision |
| `backend/harness/loop/protocol_recovery_boundary.py` | 不存在 | 新增 repair 边界 | repair payload 最小化、有限次、可审计 |
| `backend/harness/loop/closeout_boundary.py` | 不存在 | 新增统一 closeout 边界 | 所有 closeout source 统一入口 |
| `backend/harness/runtime/dynamic_context/tool_result_projector.py` | 工具结果投影 | 接入冻结预算决策 | 同结果同策略 projection 稳定 |
| `backend/harness/runtime/dynamic_context/replacement_store.py` | replacement 存储 | 保存 budget decision metadata | 可复用 frozen decision |
| `backend/harness/runtime/context_budget_policy.py` | 预算参数 | 输出 pressure boundary 所需预算 | tool trajectory / preview / protocol budgets 可追踪 |
| `backend/context_system/compaction/hooks.py` | compact hook/receipt | closeout 前 compact receipt 权威 | compact 尝试、跳过、失败均有 receipt |
| `backend/context_system/compaction/invariants.py` | compact 后协议不变量 | 扩展或复用到 follow-up recompile | orphan tool result 不进入模型 |
| `backend/runtime/context_management/session_compaction.py` | session compact | 支持 pressure-driven compact reason | compact result 可关联 tool_iteration |
| `backend/runtime/prompt_accounting/serializer.py` | prompt accounting 序列化 | 强化 repair/closeout segment accounting | 不能出现 missing segment_plan |
| `backend/runtime/prompt_accounting/stability_report.py` | cache 稳定性报告 | 增加 closeout/repair phase 维度 | 能单独看末端命中率 |
| `backend/tests/prompt_accounting_ledger_test.py` | accounting 回归 | 增加 closeout/repair scoped assertions | unplanned model call 为 0 |
| `backend/tests/tool_result_projection_regression.py` | 工具结果投影测试 | 增加 frozen budget decision 测试 | projection hash 稳定 |
| `backend/tests/harness_model_action_protocol_regression.py` | 协议回归 | 改为保护 boundary 行为 | 不保护旧内部函数形状 |

## 11. 验证矩阵

| 场景 | 期望 |
| --- | --- |
| 普通短 turn | 不触发 compact / closeout / repair |
| 多轮只读工具 follow-up | 工具结果 preview/ref 稳定 |
| 大 shell 输出 | prompt 中只保留 preview + rehydration ref |
| read_file line window | 保留 content_range 和 fresh read 条件 |
| 工具迭代接近上限 | 先产生 pressure decision |
| compact 可用 | compact 后重编 follow-up packet |
| compact invariant 失败 | 不继续工具，进入 closeout 或 block |
| protocol parse error | repair payload 最小化，attempt 计数递增 |
| protocol repair 超限 | 进入 CloseoutBoundary |
| closeout 输出工具调用 | 拒绝并 deterministic closeout |
| consecutive tool failures | 进入统一 CloseoutBoundary |
| closeout model call | 必须有 segment_plan 和 cache_metric_scope |
| prompt accounting | `unplanned_model_call` 为 0 |
| cache hit report | closeout/repair 可按 phase 单独统计 |
| warmed normal follow-up | stable prefix 命中，input miss 只来自本轮 volatile suffix |
| completion/output tokens | 单独统计，不算作 prompt cache miss |
| 普通短 turn | 不因 pressure boundary 增加模型调用或明显延迟 |
| 大量重复工具结果 | 复用 frozen budget decision，不重复写 replacement |
| compact 成本过高 | 跳过 compact 并记录 reason，不为了指标强行压缩 |
| 真实长工具任务 | closeout 触发率下降，cache 不再末端断崖下跌 |

## 12. 迁移与切换规则

### 12.1 Shadow 阶段

Phase 1 只生成 pressure decision，不改变行为。

允许：

- 写 diagnostics。
- 观察如果启用新逻辑会选择什么。

禁止：

- 改变 closeout 时机。
- 改变 repair 次数。

### 12.2 Cutover 阶段

Phase 3 后开始让 `compact_first` 影响真实执行。

Cutover 条件：

- pressure decision 测试通过。
- compact receipt 测试通过。
- prompt accounting 不出现未规划调用。
- tool call/result invariant 通过。

### 12.3 Rollback 规则

如果 Phase 3 后发现：

- compact 后模型丢失当前用户请求；
- tool result orphan；
- closeout 不再触发导致循环失控；
- prompt accounting 丢失 segment_plan；

必须回滚到 shadow mode，不允许退回“提高迭代上限”或“跳过 repair”。

### 12.4 删除规则

cutover 后必须删除：

- 旧的无边界 closeout payload 拼接逻辑。
- 旧的无 segment_plan repair model call。
- 保护旧内部函数形状的测试。
- 任何只为兼容旧 closeout 分支存在的 fallback。

允许保留：

- deterministic closeout，但只能作为最终 fallback。
- protocol repair，但必须受 ProtocolRecoveryBoundary 管理。
- tool iteration hard limit，但只能作为最终安全边界。

## 13. 指标与验收标准

### 13.1 必须指标

- `tool_limit_closeout_count`
- `protocol_repair_count`
- `admission_repair_count`
- `closeout_repair_count`
- `context_pressure_decision_count`
- `compact_attempt_count`
- `compact_applied_count`
- `compact_skipped_count`
- `compact_failed_count`
- `unplanned_model_call_count`
- `closeout_phase_cache_hit_rate`
- `repair_phase_cache_hit_rate`
- `followup_phase_cache_hit_rate`
- `stable_prefix_cache_hit_rate`
- `input_miss_tokens`
- `volatile_suffix_tokens`
- `completion_tokens`
- `model_call_count_per_turn`
- `extra_model_call_count_for_repair`
- `prompt_tokens_per_followup`
- `prompt_assembly_latency_ms_p50`
- `prompt_assembly_latency_ms_p95`
- `model_call_latency_ms_p50`
- `model_call_latency_ms_p95`
- `compaction_latency_ms_p50`
- `compaction_latency_ms_p95`
- `tool_result_projection_latency_ms_p50`
- `tool_result_projection_latency_ms_p95`
- `replacement_reuse_rate`
- `replacement_duplicate_write_count`

### 13.2 验收口径

不能用单一绝对 cache hit rate 作为唯一验收，因为 provider、上下文窗口和任务类型会影响命中率。

验收应使用相对口径：

- closeout / repair 阶段不应比前一轮正常 follow-up 出现大幅断崖式下降。
- 同类长工具任务中，hard closeout 触发次数应下降。
- 达到工具压力时，日志中应先出现 pressure decision 和 compact receipt。
- 所有主链路 model call 均可被 prompt accounting 归因。
- warmed normal follow-up 的输入 miss 应主要来自 current user、latest tool observation、runtime control suffix。
- completion/output tokens 必须单独统计，不能混入 prompt cache miss。
- 普通短 turn 和正常 follow-up 不能增加额外模型调用。
- p50 / p95 延迟不能因新增边界明显回退；若 provider 波动导致变化，必须用同样本对照说明。
- replacement reuse rate 应上升，duplicate replacement writes 应接近 0。

建议初始目标：

- `unplanned_model_call_count = 0`
- `compact_attempt_count > 0` when `tool_iteration >= max - 1`
- `repair_count` 不随 closeout 成倍增长
- closeout / repair 命中率相对上一轮 follow-up 的下降幅度控制在可解释范围内，并通过 segment stability report 说明原因
- warmed follow-up 中稳定段 hash 不变时，stable prefix cache hit 应接近 provider 可达到上限。
- input miss tokens 的增长应与本轮新增 volatile suffix 大小匹配。
- 同类长工具任务的总 prompt tokens、repair 模型调用次数、hard closeout 次数不高于基线，理想情况下下降。
- 普通短 turn 的 p95 latency 不高于基线；工具长任务的总耗时应因减少无效 prompt 和 repair/closeout 调用而下降。

### 13.3 性能硬门槛

以下任一情况出现，不能判定计划实施成功：

- 缓存命中率上升，但 `model_call_count_per_turn` 上升。
- 缓存命中率上升，但普通短 turn p95 latency 明显回退。
- 缓存命中率上升，但总 prompt tokens 不降反升。
- closeout 触发率下降，但只是因为工具迭代上限提高。
- compact 次数上升，但 hard closeout、repair 次数和 prompt tokens 没有下降。
- replacement 文件数量快速增长，但 reuse rate 没有同步上升。
- repair payload 更结构化了，但仍携带完整工具轨迹或完整 history。

性能验收必须采用同类任务对照，至少比较：

```text

before:
  prompt tokens
  cached tokens
  input miss tokens
  completion tokens
  model call count
  repair count
  closeout count
  p50/p95 latency
  replacement writes

after:
  same metrics

pass condition:
  stable prefix hit improves or remains provider-maximal
  input miss is bounded to volatile suffix
  no extra normal-path model calls
  latency does not regress
  prompt tokens and repair/closeout overhead decrease on long tasks

```

## 14. 禁止捷径

- 禁止只提高 `_MAX_SINGLE_TURN_TOOL_ITERATIONS`。
- 禁止删除 `tool-limit-closeout`。
- 禁止删除 `repair`。
- 禁止用 prompt 文案代替结构边界。
- 禁止把完整工具轨迹塞进 repair prompt。
- 禁止 closeout 阶段继续请求工具。
- 禁止 compact 后不验证 tool call / tool result 配对。
- 禁止保留无 segment_plan 的模型调用。
- 禁止为了测试通过跳过失败路径。
- 禁止保留旧兼容分支继续影响主路径。
- 禁止让 `single_agent_turn.py` 继续同时拥有观察、决策、恢复、收口全部权威。
- 禁止用额外模型调用换取表面缓存命中率。
- 禁止每轮无条件 compact。
- 禁止每轮全量扫描历史 runtime_state 或 prompt accounting。
- 禁止重复写入同内容 replacement。
- 禁止把 output/completion tokens 统计成 prompt cache miss。

## 15. 预期结果

修复完成后，系统应具备以下性质：

- `tool-limit-closeout` 和 `repair` 仍然存在，但触发频率降低。
- 工具循环接近压力上限时，优先 compact / recompile / continue。
- 工具结果 preview、replacement、rehydration ref 在 follow-up 中稳定。
- repair 只修协议，不重写任务目标。
- closeout 只收口，不再继续工具循环。
- 所有 model call 都有 segment_plan、cache_metric_scope 和 prompt accounting 记录。
- `single_agent_turn.py` 从“大而全决策中心”降级为 runtime orchestrator。
- 缓存低命中的问题可以通过 phase/source/segment 定位，而不是靠人工猜。
- warmed follow-up 接近成熟 agent 表现：稳定输入前缀命中，本轮新增尾部允许 miss，输出 token 单独统计。
- 修复后性能不退化：普通路径无额外模型调用，长工具任务减少无效 prompt、repair 和 hard closeout 开销。

最终目标不是让末端阶段永远不掉命中率，而是让掉点变得少、可解释、可追踪，并且不再由 closeout / repair 承担本该由上下文治理承担的工作。
