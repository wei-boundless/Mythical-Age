# Dynamic Prompts 装配系统升级计划书（2026-05-31）

## 0. 结论

当前 prompts 系统已经完成了第一阶段的方向性收敛：

- 模型真实输入统一为 `RuntimeInvocationPacket.model_messages`。
- `system_instructions` 旧预览字段已清理。
- `segment_plan` 已能标记 `cache_role`、`cache_scope`、`compression_role`。
- stable payload 已开始从完整系统对象转向 model-visible projection。

但当前系统仍缺一个成熟 agent 必须具备的核心层：

```text
Dynamic Prompt Context Manager
```

也就是在模型调用前，专门负责治理动态上下文的结构化管线。它要控制 `history`、`observations`、`execution_state`、`work_history`、`runtime_context` 这些高频变化内容如何进入模型，避免它们膨胀、重复、冲突或破坏 cache。

本计划目标不是再写几句 prompt，也不是继续在 `RuntimeCompiler` 里堆字段压缩函数，而是建立一个可以长期演进的动态上下文装配系统。

## 1. 技术来源报告

### 1.1 当前项目代码依据

当前主链路：

```text
backend/harness/runtime/assembly.py
-> backend/harness/runtime/compiler.py
-> RuntimeInvocationPacket.model_messages
-> backend/harness/loop/agent_loop.py / task_executor.py
-> model gateway
```

当前 prompt library：

```text
backend/prompt_library/models.py
backend/prompt_library/assembly.py
backend/prompt_library/packs.py
backend/prompt_library/manifest.py
```

当前 runtime prompt message 结构：

```text
global_static
task_stable
skill_candidates / active_skills
agent_stable
environment_stable
dynamic_projection
volatile_user / volatile_task_state / tool_observations
```

当前高风险动态入口：

```text
compile_turn_action_packet:
  volatile_payload.history = raw history
  volatile_payload.user_message = current user message

compile_task_execution_packet:
  volatile_payload.execution_state = raw execution_state
  volatile_payload.observations = projected observations
  volatile_payload.work_history = _work_rollout_payload(work_rollout)

compile_observation_followup_packet:
  volatile_payload.history = raw history
  volatile_payload.observations = projected observations

_runtime_context_payload:
  runtime refs / storage / policy hashes / agent_visible_runtime_projection
```

当前已做对的部分：

- `operation_authorization` 已支持 model-visible summary。
- `runtime_envelope` 已有 `_runtime_envelope_model_visible()`。
- `observations` 已有 `_observations_model_visible_payload()`，会压缩 summary/error。
- `prompt_manifest.token_estimate` 已记录 `model_visible_chars`、`cacheable_prefix_chars`、`volatile_chars`。

当前主要缺口：

- 没有统一的动态上下文管理层。
- `history` 没有 compaction / pinned facts / recent turns 分层。
- `execution_state` 原样进入模型。
- `work_history` 虽然限制最近 18 条，但字段级不受控。
- `runtime_context` 中稳定字段和动态字段混在 volatile message 里。
- observation 投影没有按 `observation_id + content_hash + projection_policy` 复用，不能保证同一观察的投影字节稳定。
- volatile section 没有强制记录“为什么必须 volatile”。

### 1.2 Codex 源码参考

本地源码位置：

```text
D:\AI应用\openai-codex\codex-rs\core\src\context_manager\history.rs
D:\AI应用\openai-codex\codex-rs\core\src\context_manager\updates.rs
D:\AI应用\openai-codex\codex-rs\core\src\compact.rs
D:\AI应用\openai-codex\codex-rs\core\src\compact_remote.rs
D:\AI应用\openai-codex\codex-rs\core\src\state\auto_compact_window.rs
```

可借鉴机制：

1. ContextManager 是历史的权威，不把 raw history 直接给模型。
2. 发送前执行 normalization，保证 call/output 成对、孤儿 output 被移除、不支持图片时移除图片。
3. 工具输出用统一 truncation policy，而不是每个调用点自己截断。
4. 环境、权限、模式等上下文用 reference context 做 diff，不是每轮全量重注入。
5. compaction 是正式生命周期：有 trigger、reason、phase、implementation、pre/post hook、analytics。
6. compaction 成功后安装 replacement history，而不是“旧 history + summary”并存。
7. auto compact window 记录 prefill baseline，用于判断当前窗口的真实增长。

不直接照搬的部分：

- Codex 使用 Responses/remote compact 的具体 API 形态，本项目不必复制。
- Codex 面向 coding agent 的环境上下文，本项目是通用 agent，需要抽象成 task environment / runtime environment 通用机制。
- Codex 的 protocol item 类型较重，本项目应使用较轻的 dataclass/dict projection，避免把 runtime 复杂度拉满。

### 1.3 Claude Code 参考

本地源码/资料位置：

```text
D:\AI应用\claude-code-nb-main\constants\systemPromptSections.ts
D:\AI应用\claude-code-nb-main\constants\prompts.ts
D:\AI应用\claude-code-nb-main\utils\api.ts
D:\AI应用\claude-code-nb-main\query.ts
D:\AI应用\claude-code-nb-main\utils\toolResultStorage.ts
D:\AI应用\Claude-Code-Source-Study-main\docs\04-System-Prompt-工程.md
D:\AI应用\Claude-Code-Source-Study-main\docs\05-对话循环.md
```

可借鉴机制：

1. System prompt 有显式 `SYSTEM_PROMPT_DYNAMIC_BOUNDARY`。
2. 动态 section 不是都每轮重算；`systemPromptSection()` 会 session memoize。
3. 真正每轮变化的 section 必须使用 `DANGEROUS_uncachedSystemPromptSection(..., reason)`，强制写明原因。
4. 模型调用前有多级预处理管线：

```text
applyToolResultBudget
-> snipCompactIfNeeded
-> microcompact
-> contextCollapse
-> autocompact
-> callModel
```

5. 大工具结果不是直接塞进 prompt，而是落盘，只给模型路径、大小、预览。
6. tool result replacement decision 会持久化，保证 resume/fork 后替换结果字节一致，保护 prompt cache。

不直接照搬的部分：

- Claude Code 的 global system prompt boundary 是 Anthropic system prompt 形态；本项目已采用 `model_messages + segment_plan`，不需要退回单个 system prompt。
- Claude Code 的 feature gate / GrowthBook 体系不适合本项目。
- 工具结果落盘可以借鉴，但本项目已有 artifacts/storage/task environment，需要接入项目自己的 artifact/reference 体系。

## 2. 当前问题定义

### 2.1 系统属性缺失

当前缺失的不是“prompt 太长”这个表面问题，而是：

```text
动态模型上下文没有单一权威管理层。
```

结果是：

- compiler 同时负责组装、压缩、投影、排序、cache 标记。
- 不同动态字段采用不同压缩策略。
- raw state 容易绕过投影直接进入模型。
- 长任务过程中历史和观察会持续膨胀。
- 同一事实可能同时出现在 observation、work_history、execution_state、runtime_context。
- dynamic 字段中混有 session-stable 信息，降低缓存收益。

### 2.2 正确终态

正确终态应是：

```text
Raw Runtime Ledger
-> Dynamic Context Manager
-> Stable/Dynamic Projection Packet
-> RuntimeCompiler
-> model_messages + segment_plan
-> Prompt Accounting / Audit
```

其中：

- Raw ledger 保存完整事实。
- Dynamic Context Manager 负责裁剪、摘要、替换、去重、差分。
- RuntimeCompiler 只消费投影结果，不直接读取 raw history / raw execution_state。
- Prompt manifest 能解释每个 dynamic segment 为什么存在、体积多少、是否可压缩。

## 3. 目标架构

### 3.1 新增核心模块

建议新增：

```text
backend/harness/runtime/dynamic_context/
  __init__.py
  models.py
  manager.py
  history_projector.py
  observation_projector.py
  execution_state_projector.py
  work_history_projector.py
  runtime_delta_projector.py
  replacement_store.py
  token_budget.py
```

职责：

| 模块 | 职责 | 禁止事项 |
| --- | --- | --- |
| `models.py` | 定义动态上下文输入/输出合同 | 不访问文件、不读全局状态 |
| `manager.py` | 编排投影管线，输出 `DynamicContextProjection` | 不直接调用模型 |
| `history_projector.py` | raw history -> pinned/recent/summary/context updates | 不处理 tool output 细节 |
| `observation_projector.py` | observations -> stable observation projection | 不决定 agent 下一步动作 |
| `execution_state_projector.py` | execution_state -> 白名单状态摘要 | 不透传任意 dict |
| `work_history_projector.py` | work rollout -> recent progress / active facts / artifact refs | 不保存完整流水账 |
| `runtime_delta_projector.py` | runtime baseline/delta | 不重复 stable payload |
| `replacement_store.py` | 保存 tool/observation 投影替换结果 | 不改变真实 artifact |
| `token_budget.py` | 字符/token 预算、告警、降级策略 | 不自行删除合同必需事实 |

### 3.2 核心数据结构

#### DynamicContextInput

```python
@dataclass(frozen=True)
class DynamicContextInput:
    invocation_kind: str
    session_id: str
    turn_id: str = ""
    task_run_id: str = ""
    history: tuple[dict[str, Any], ...] = ()
    observations: tuple[dict[str, Any], ...] = ()
    execution_state: dict[str, Any] = field(default_factory=dict)
    work_rollout: dict[str, Any] = field(default_factory=dict)
    runtime_assembly: dict[str, Any] = field(default_factory=dict)
    runtime_envelope: dict[str, Any] = field(default_factory=dict)
    current_user_message: str = ""
    projection_policy: dict[str, Any] = field(default_factory=dict)
```

#### DynamicContextProjection

```python
@dataclass(frozen=True)
class DynamicContextProjection:
    stable_runtime_delta: dict[str, Any]
    dynamic_runtime_projection: dict[str, Any]
    volatile_request_projection: dict[str, Any]
    volatile_state_projection: dict[str, Any]
    observation_refs: tuple[str, ...]
    context_refs: tuple[str, ...]
    artifact_refs: tuple[str, ...]
    budget_report: dict[str, Any]
    section_reports: tuple[dict[str, Any], ...]
    authority: str = "harness.runtime.dynamic_context.projection"
```

#### VolatileSectionReport

每个 volatile section 必须记录：

```python
{
  "section_id": "...",
  "source": "history|observations|execution_state|work_history|runtime_delta",
  "volatility_reason": "...",
  "input_chars": 0,
  "output_chars": 0,
  "projection_strategy": "...",
  "cache_impact": "volatile",
  "refs": [...]
}
```

没有 `volatility_reason` 的 dynamic/volatile section 不允许进入最终 packet。

### 3.3 Prompt 分层目标

目标分层：

```text
global_static:
  runtime protocol prompt

session_stable:
  stable task environment projection
  stable tool catalog summary
  agent role prompt
  environment prompt
  skill candidates

task_stable:
  task contract
  active skills
  task stable metadata

dynamic_projection:
  runtime delta
  operation authorization summary
  active policy changes
  current task lifecycle projection

volatile_state:
  current user message
  recent turns
  current observations
  current execution state
  active failures
  active work facts
```

### 3.4 RuntimeCompiler 的目标职责

`RuntimeCompiler` 最终只负责：

1. 调用 prompt library 组装 stable prompt sections。
2. 调用 dynamic context manager 获取动态投影。
3. 把 stable/dynamic/volatile 投影排成 `model_messages`。
4. 生成 `segment_plan`。
5. 生成 `prompt_manifest`。

它不再负责：

- raw history 压缩。
- observation 摘要策略。
- work history 截断。
- execution state 白名单。
- runtime baseline/delta 判断。

## 4. 固定执行流

### 4.1 Turn Action

```text
input:
  user_message
  raw history
  runtime_assembly
  runtime_envelope

flow:
  1. RuntimeCompiler builds stable payload.
  2. DynamicContextManager projects history + runtime delta + current request.
  3. RuntimeCompiler creates model_messages.
  4. Prompt manifest records stable/dynamic/volatile budgets.

output messages:
  global_static
  turn_action_stable_contract
  skill_candidates
  agent_stable
  environment_stable
  dynamic_runtime_projection
  volatile_current_request
```

### 4.2 Task Execution

```text
input:
  task_run
  task_contract
  observations
  execution_state
  work_rollout
  runtime_assembly
  runtime_envelope

flow:
  1. Stable task contract remains cacheable within task.
  2. DynamicContextManager projects observations, execution_state, work_rollout.
  3. ReplacementStore reuses prior observation/tool projections when content hash unchanged.
  4. RuntimeCompiler emits task_execution model_messages.

output messages:
  global_static
  task_stable_contract
  agent_stable
  active_skills
  environment_stable
  dynamic_runtime_projection
  volatile_task_state
```

### 4.3 Observation Followup

```text
input:
  current user message
  raw history
  observations
  runtime_assembly
  runtime_envelope

flow:
  1. Observations go through ObservationProjector.
  2. History goes through HistoryProjector.
  3. Runtime delta remains compact.
  4. The model sees latest observation projection and enough recent history to answer or continue.
```

## 5. 投影策略

### 5.1 HistoryProjector

输入：

```text
raw history
current user message
session/task context
```

输出：

```text
{
  "context_summary": "...",
  "pinned_facts": [...],
  "recent_turns": [...],
  "active_tool_trajectory": [...],
  "omitted_history": {"turn_count": N, "reason": "..."}
}
```

规则：

- 普通 turn 最多保留最近 6 个 message-equivalent 单元。
- 工具调用轨迹必须保持 call/result 配对。
- 被 compact 的历史用 `context_summary` 替代。
- 用户当前消息永远不被 compact。
- 不允许 raw history 直接进入 compiler。

### 5.2 ObservationProjector

输入：

```text
raw observations
projection policy
replacement store
```

输出：

```text
{
  "latest_observations": [...],
  "active_failures": [...],
  "historical_failures": [...],
  "artifact_evidence": [...],
  "omitted_observations": {...}
}
```

规则：

- 最新 observation 优先保留。
- 同类历史失败合并。
- 结构化错误保留 `code/message/retryable/origin`。
- 大内容使用 preview + ref。
- 同一 `observation_id + content_hash + policy_hash` 必须生成相同 projection。

### 5.3 ExecutionStateProjector

输入：

```text
execution_state
task_run diagnostics
```

输出：

```text
{
  "runtime_status": "...",
  "current_step": {...},
  "pending_user_steers": [...],
  "active_contract_revisions": [...],
  "recoverable_error": {...},
  "validation_status": {...}
}
```

规则：

- 默认 deny all，字段白名单进入。
- 不允许完整 execution_state 进入模型。
- 大字段必须落到 refs。
- pending user steer 必须高于普通 observation。

### 5.4 WorkHistoryProjector

输入：

```text
work_rollout
artifact refs
model_visible_history
```

输出：

```text
{
  "latest_progress": "...",
  "active_facts": [...],
  "recent_steps": [...],
  "active_artifacts": [...],
  "checkpoint": {...},
  "omitted_work_history": {...}
}
```

规则：

- recent steps 默认最多 8 条。
- 每条 summary 限制字符数。
- artifact refs 分级：
  - entry artifacts
  - recently changed artifacts
  - required verification artifacts
  - archived artifact refs
- 不能把文档清单当真实 artifact evidence。

### 5.5 RuntimeDeltaProjector

输入：

```text
runtime_assembly
runtime_envelope
previous runtime baseline
```

输出：

```text
{
  "current_runtime": {...},
  "runtime_delta": {...},
  "operation_authorization": {...},
  "policy_refs": {...}
}
```

规则：

- session-stable refs 不放进 volatile。
- mode/profile/environment 变化才发 delta。
- operation authorization 默认 summary。
- 完整权限决策只保存在 trace，不进 model messages。

## 6. 分阶段实施计划

### Phase 1：建立动态上下文模型与审计

目标：

- 新增动态上下文数据结构。
- 让每个 dynamic/volatile section 都有报告。
- 不改变模型行为，只做 shadow projection。

文件：

```text
backend/harness/runtime/dynamic_context/models.py
backend/harness/runtime/dynamic_context/token_budget.py
backend/scripts/inspect_runtime_prompt_packet.py
backend/tests/dynamic_prompt_context_projection_test.py
```

完成标准：

- 能从现有 packet 输出每段 `input_chars/output_chars/cache_role/volatility_reason`。
- `prompt_manifest` 增加 `dynamic_context_report`。
- 不改变现有 `model_messages` 内容。

### Phase 2：ObservationProjector 接入

目标：

- 从 compiler 中移出 `_observations_model_visible_payload()`。
- 建立稳定 observation projection。
- 增加 replacement cache。

文件：

```text
backend/harness/runtime/dynamic_context/observation_projector.py
backend/harness/runtime/dynamic_context/replacement_store.py
backend/harness/runtime/compiler.py
backend/tests/observation_projection_regression.py
```

完成标准：

- 大 observation 不会全量进入模型。
- 同一 observation 重复编译输出字节一致。
- structured error 不丢失。
- 历史失败和当前失败分层。

### Phase 3：ExecutionStateProjector 接入

目标：

- compiler 不再直接 `dict(execution_state)`。
- execution state 进入模型前必须白名单投影。

文件：

```text
backend/harness/runtime/dynamic_context/execution_state_projector.py
backend/harness/runtime/compiler.py
backend/tests/execution_state_projection_regression.py
```

完成标准：

- 任意未知 execution_state 大字段不进入模型。
- pending steers / contract revisions / recoverable error 可见。
- 测试覆盖大字段被 ref/omit。

### Phase 4：WorkHistoryProjector 接入

目标：

- 替换 `_work_rollout_payload()` 直接进入模型的路径。
- 长任务历史按 recent/active/artifact/checkpoint 分层。

文件：

```text
backend/harness/runtime/dynamic_context/work_history_projector.py
backend/harness/runtime/compiler.py
backend/tests/work_history_projection_regression.py
```

完成标准：

- `model_visible_history` 不超过策略上限。
- 每条 summary 有字符上限。
- artifact refs 被分级。
- work history 不能无限增长。

### Phase 5：HistoryProjector 接入 turn/followup

目标：

- 普通对话和 observation followup 不再 raw history 全量进入。
- 建立 recent turns + pinned facts + context summary。

文件：

```text
backend/harness/runtime/dynamic_context/history_projector.py
backend/harness/runtime/compiler.py
backend/tests/history_projection_regression.py
```

完成标准：

- raw history 超长时自动投影。
- 最近对话保留。
- 当前用户消息不丢。
- 工具 call/result 不被拆坏。

### Phase 6：RuntimeDeltaProjector 接入

目标：

- 将 `_runtime_context_payload()` 拆为 stable baseline 和 dynamic delta。
- dynamic projection 只保留真正变化的信息。

文件：

```text
backend/harness/runtime/dynamic_context/runtime_delta_projector.py
backend/harness/runtime/compiler.py
backend/tests/runtime_delta_projection_regression.py
```

完成标准：

- agent/env refs、storage、policy hash 不再重复塞进 volatile。
- mode/profile/environment 变化时能生成 delta。
- operation authorization summary 不回退成完整 deny 明细。

### Phase 7：DynamicContextManager 总装

目标：

- compiler 只调用一个 manager。
- 各 projector 的输出统一成 `DynamicContextProjection`。

文件：

```text
backend/harness/runtime/dynamic_context/manager.py
backend/harness/runtime/compiler.py
backend/tests/dynamic_context_manager_integration_test.py
```

完成标准：

- `compile_turn_action_packet`、`compile_task_execution_packet`、`compile_observation_followup_packet` 都通过 manager 获取动态投影。
- compiler 中不再出现 raw `history`、raw `execution_state`、raw `work_rollout` 进入 payload。
- `prompt_manifest.dynamic_context_report` 完整。

### Phase 8：Compaction / Replacement History 生命周期

目标：

- 长任务和长会话支持正式 compact。
- compact 后安装 replacement history，而不是 summary + old history 并存。

文件：

```text
backend/harness/runtime/dynamic_context/compaction.py
backend/harness/runtime/dynamic_context/replacement_store.py
backend/harness/loop/agent_loop.py
backend/harness/loop/task_executor.py
backend/runtime/prompt_accounting/*
backend/tests/dynamic_context_compaction_regression.py
```

完成标准：

- compact 有 trigger/reason/phase/status。
- compact 失败不会破坏当前上下文。
- compact 成功后后续 packet 不包含被替换的旧历史。
- prompt accounting 能记录 compact 前后 dynamic token 变化。

## 7. 文件级执行清单

### 新增

```text
backend/harness/runtime/dynamic_context/__init__.py
backend/harness/runtime/dynamic_context/models.py
backend/harness/runtime/dynamic_context/manager.py
backend/harness/runtime/dynamic_context/history_projector.py
backend/harness/runtime/dynamic_context/observation_projector.py
backend/harness/runtime/dynamic_context/execution_state_projector.py
backend/harness/runtime/dynamic_context/work_history_projector.py
backend/harness/runtime/dynamic_context/runtime_delta_projector.py
backend/harness/runtime/dynamic_context/replacement_store.py
backend/harness/runtime/dynamic_context/token_budget.py
backend/harness/runtime/dynamic_context/compaction.py
```

### 修改

```text
backend/harness/runtime/compiler.py
backend/harness/runtime/prompt_segment_plan.py
backend/prompt_library/manifest.py
backend/scripts/inspect_runtime_prompt_packet.py
backend/runtime/prompt_accounting/serializer.py
backend/runtime/prompt_accounting/ledger.py
backend/harness/loop/agent_loop.py
backend/harness/loop/task_executor.py
```

### 测试

```text
backend/tests/dynamic_prompt_context_projection_test.py
backend/tests/observation_projection_regression.py
backend/tests/execution_state_projection_regression.py
backend/tests/work_history_projection_regression.py
backend/tests/history_projection_regression.py
backend/tests/runtime_delta_projection_regression.py
backend/tests/dynamic_context_manager_integration_test.py
backend/tests/dynamic_context_compaction_regression.py
```

## 8. 验证矩阵

### 8.1 静态结构验证

```text
python -m py_compile backend\harness\runtime\compiler.py
python -m pytest backend\tests\prompt_library_runtime_pack_test.py -q
python -m pytest backend\tests\prompt_accounting_ledger_test.py -q
```

检查：

- `model_messages` 仍是唯一模型输入。
- `segment_plan` 中所有 volatile section 都有 report。
- stable segment 不包含 history/observations/execution_state/work_history。

### 8.2 动态体积验证

用 `inspect_runtime_prompt_packet.py` 检查：

```text
model_visible_chars
cacheable_prefix_chars
volatile_chars
per-section chars
top dynamic fields
```

目标阈值：

- 普通 turn：volatile chars 稳定低于 4K，除非用户当前消息本身很长。
- observation followup：单轮 observation projection 默认低于 4K。
- task execution：无大文件观察时 volatile chars 默认低于 8K。
- 长任务多轮后 volatile chars 不随历史线性增长。

### 8.3 行为验证

必须实测：

1. 普通对话，不启动 task。
2. 联网搜索，工具观察正常回灌。
3. 工具失败后，structured error 进入下一轮。
4. 长任务多轮执行，work history 不线性膨胀。
5. 用户中途修改要求，pending steer 高优先级进入 volatile state。
6. 大工具输出落 refs/preview，不全量进入 prompt。
7. compact 成功后旧 history 被 replacement history 替换。

## 9. Cutover 规则

### 9.1 Shadow 模式

Phase 1-4 允许 shadow：

- 生成新 projection report。
- 不改变模型输入。
- 与旧 compiler 输出并行对比。

### 9.2 Partial Cutover

Phase 2 起每个 projector 单独 cutover：

```text
observations -> projected observations
execution_state -> projected execution state
work_history -> projected work history
history -> projected history
runtime_context -> baseline/delta
```

每个 cutover 必须满足：

- 有回归测试。
- audit script 能显示体积下降或稳定。
- 行为测试没有丢关键事实。

### 9.3 禁止长期双链路

不允许长期保留：

```text
raw observations path + projected observations path
raw execution_state path + projected execution_state path
raw history path + projected history path
```

shadow 只允许作为实施阶段过渡。阶段完成后旧 raw path 必须删除。

### 9.4 Rollback

如果某个 projector 导致真实能力下降，只回滚该 projector 的 cutover，不回滚整个 dynamic context manager。

回滚条件必须明确：

- 模型无法看到必要错误。
- 用户 steer 丢失。
- artifact evidence 丢失。
- 工具 call/result 结构被破坏。
- 长任务不能继续。

## 10. 禁止事项

实施时禁止：

1. 用关键词判断是否压缩或保留。
2. 用 prompt 文案替代结构化 projection。
3. 把 raw dict 改名后继续塞进模型。
4. 因兼容保留双路径不清理。
5. 在 compiler 里继续堆各类 `_xxx_payload()` 补丁。
6. 把 trace/debug/manifest 字段暴露给模型。
7. compact 后保留旧 history 同时再加 summary。
8. 丢失 tool call/result 配对。
9. 丢失当前用户消息、pending steer、active failure。
10. 为了通过测试降低断言或删除关键失败用例。

## 11. 与现有计划的关系

已有 `prompts_system_optimization_plan_20260531.md` 主要解决：

- stable payload 过重。
- tool catalog 过重。
- operation authorization 暴露过多。
- environment projection 过重。
- runtime prompt 噪声。

本计划补充的是更深一层：

```text
动态上下文生命周期和投影治理。
```

两者关系：

```text
prompts_system_optimization_plan:
  清理 prompt 装配表面和 stable/dynamic 分段

dynamic_prompt_context_manager_upgrade_plan:
  建立动态内容进入模型前的正式管理层
```

实施顺序应为：

1. 完成 stable payload 和 manifest 已开始的清理。
2. 建立 DynamicContextManager shadow。
3. 按 observation -> execution_state -> work_history -> history -> runtime_delta 顺序 cutover。
4. 最后做 compaction/replacement history。

## 12. 最终验收标准

系统升级完成后，应满足：

1. `RuntimeCompiler` 不直接把 raw dynamic state 放进 `model_messages`。
2. 每个 volatile section 都有明确 source、reason、budget、projection strategy。
3. history、observations、execution_state、work_history 都有独立 projector。
4. 同一 observation/tool result 的投影可稳定复用。
5. stable payload 不含高频动态字段。
6. dynamic payload 不含可稳定缓存的重复配置字段。
7. 长任务多轮执行后 prompt 体积不随历史线性增长。
8. compact 是正式生命周期事件，有可审计状态和 replacement history。
9. prompt audit 能解释每个 segment 为什么存在、从哪里来、体积多少、是否可缓存。
10. 实测普通对话、搜索、工具失败恢复、长任务续跑、用户中途 steering 均正常。

达到这些标准后，prompts 装配系统才算从“能工作”升级为“可精密运转”。
