# TaskRun Observation Ledger 与恢复上下文修复设计书

日期：2026-05-28

状态：待实施设计稿

适用范围：

```text
backend/harness/loop/task_executor.py
backend/harness/runtime/compiler.py
backend/harness/runtime/invocation_packet.py
backend/runtime/memory/tool_observation_ledger.py
backend/runtime/memory/evidence_packet.py
backend/runtime/context_management/tool_use_summary.py
backend/runtime/tool_runtime/tool_executor.py
backend/runtime/tool_runtime/native_tools.py
backend/tests/query_runtime_runtime_loop_regression.py
backend/tests/sandbox_tool_runtime_regression.py
backend/tests/tool_observation_ledger_regression.py
```

本文只解决一个核心问题：TaskRun 在长期执行、工具失败、系统修复、续跑和恢复时，如何把工具调用记录、失败记录和真实产物证据交给 agent，而不让旧失败污染当前判断。

## 1. 当前问题

当前 `backend/harness/loop/task_executor.py` 的主链是：

```text
execute_task_run
-> compile_task_execution_packet(observations)
-> agent 输出 ModelActionRequest
-> admit_model_action
-> _execute_task_tool_call
-> 记录 observation
-> 下一轮把 observations 再交给 agent
```

这个方向是正确的：agent 根据 observation 自己判断下一步，而不是系统替 agent 修产物。

但 observation 复用策略还不成熟：

```python
def _reusable_observations(runtime_host, task_run_id):
    return [
        item
        for item in _existing_observations(runtime_host, task_run_id)
        if not item.get("error") and str(item.get("observation_type") or "") != "executor_error"
    ]
```

这个策略有两个问题：

1. 它把失败观察全部丢掉，agent 失去修复依据。
2. 如果改成全部保留，旧 runtime/config 下的失败又会污染恢复后的当前判断。

五层地下塔长任务暴露出的真实故障是：

```text
旧 image_generate 配置失败被记录为 observation。
系统修复 image_generate 后重启执行器。
恢复时旧失败仍被 agent 理解为当前工具不可用。
agent 由此 block，而不是重新尝试或改用当前可用工具。
```

这说明缺的不是“是否把失败发给 agent”，而是一个成熟的 observation ledger 与 context projection 机制。

### 1.1 项目内已有资源

本项目已经有几块相关资产，修复方案必须复用和扩展它们，不能在 `task_executor.py` 里平行造第二套账本：

| 现有资源 | 文件 | 当前能力 | 缺口 |
| --- | --- | --- | --- |
| `ToolResultEnvelope` | `backend/runtime/tool_runtime/tool_result_envelope.py` | 包装工具状态、文本、结构化 payload、路径、artifact、command receipt | error 还偏字符串，缺少 error code/origin/retryable |
| `ToolObservationLedger` / `ToolObservationRecord` | `backend/runtime/memory/tool_observation_ledger.py` | 从工具结果构建读、写、验证、委派证据，支持 obligation validation | 缺少 runtime fingerprint、validity、historical/active failure 分层 |
| `EvidencePacket` | `backend/runtime/memory/evidence_packet.py` | 把 observations 转为 facts、limitations、deliverable coverage | 偏验收证据，不负责恢复上下文有效性 |
| `ToolUseSummary` | `backend/runtime/context_management/tool_use_summary.py` | 将 tool_result 压缩为 summary/facts/unknowns/limitations | 只能做摘要，不应做权限和 freshness 裁决 |
| `context_compactor_agent` | `backend/agent_system/profiles/runtime_profile_registry.py` | model-only 上下文压缩 agent，无工具调用 | 适合长历史压缩，不适合决定工具失败是否仍有效 |
| `memory_search_agent` / `memory_system_agent` | 同上 | 记忆检索与记忆候选维护 | 可提供历史经验和用户偏好，不应覆盖系统当前 runtime 状态 |

因此，目标不是新增一个脱离项目的 `ObservationRecord` 子系统，而是：

```text
Raw Runtime Events
-> ToolResultEnvelope
-> ToolObservationRecord/ToolObservationLedger
-> Observation Freshness Extension
-> TaskObservationProjection
-> optional Context/Memory Subagent Summary
-> RuntimeInvocationPacket
```

## 2. 成熟 agent 对照原则

成熟 agent harness 不应该把历史消息、工具结果、错误文本无差别塞回模型。更合理的结构是：

```text
Raw Execution Ledger
-> Observation Normalization
-> Validity / Freshness Classification
-> Runtime Context Projection
-> Agent Recovery Decision
```

对应职责：

| 层 | 权限 | 不允许做的事 |
| --- | --- | --- |
| Raw Execution Ledger | 永久记录真实发生过的 action、observation、error、artifact receipt | 删除历史、改写历史 |
| Observation Normalization | 把工具结果、错误、产物、门禁裁决统一成结构化记录 | 用关键词判断语义任务 |
| Validity Classification | 判断记录对当前 runtime 是否仍有效、是否可复用、是否只作为历史 | 替 agent 决定下一步 |
| Runtime Context Projection | 给 agent 当前步骤所需的事实、失败、待修复项、产物证据 | 把所有历史噪声原样塞入上下文 |
| Agent Recovery Decision | agent 根据当前投影决定重试、换工具、修参数、问用户、block 或完成 | 系统替 agent 手工修 artifact |

关键结论：

```text
失败记录必须保留。
失败记录应该给 agent 看。
但失败记录必须带生命周期状态，不能伪装成当前事实。
```

## 3. 目标结构

TaskRun 的 observation 数据分三种视图：

### 3.1 原始账本 Raw Ledger

原始账本记录所有事件，不做删除：

```json
{
  "observation_id": "rtobs:...",
  "task_run_id": "taskrun:...",
  "request_ref": "model-action:...",
  "directive_ref": "runtime-directive:...",
  "observation_type": "tool_result",
  "source": "tool:image_generate",
  "created_at": 1770000000.0,
  "payload": {},
  "error": ""
}
```

原始账本用于审计、回放、调试、最终验收，不直接作为 agent 上下文。

### 3.2 规范化记录 ToolObservationRecord 扩展

每条 tool observation 在进入 TaskRun 上下文前，优先通过现有 `build_tool_observation_record()` 规范化。它已经能产生：

```json
{
  "observation_ref": "rtobs:...",
  "tool_name": "image_generate",
  "tool_args": {},
  "result_preview": "...",
  "side_effect_kind": "read | write | verification | delegation | repair",
  "satisfies": [],
  "status": "ok | error",
  "observed_paths": [],
  "matched_paths": [],
  "artifact_refs": [],
  "command_receipt": {},
  "side_effect_hash": "...",
  "evidence_source": "structured_envelope | legacy_text"
}
```

这层继续作为项目的工具证据账本，不另建平行结构。需要补充的是 freshness / validity 扩展字段：

```json
{
  "runtime_freshness": {
    "fingerprint": {
      "runtime_assembly_id": "...",
      "tool_registry_hash": "...",
      "tool_config_hash": "...",
      "sandbox_policy_hash": "...",
      "permission_policy_hash": "...",
      "backend_config_hash": "..."
    },
    "visibility": "active | historical | superseded",
    "reuse_as_fact": true,
    "reuse_as_repair_context": false,
    "reason": "current_success"
  },
  "structured_error": {
    "code": "upstream_504",
    "message": "Gateway timeout",
    "retryable": true,
    "origin": "tool_provider | operation_gate | model_runtime | validator"
  }
}
```

字段要求：

| 字段 | 要求 |
| --- | --- |
| `status` | 沿用 `ToolResultEnvelope.status` / `ToolObservationRecord.status`，不能靠关键词覆盖结构化状态 |
| `artifact_refs` | 沿用现有 ledger 提取规则，只从 envelope、structured payload、明确 artifact 字段提取 |
| `structured_error.retryable` | 来自 provider/gate/model runtime 的结构化错误，不靠文案猜测 |
| `runtime_freshness.fingerprint` | 用于判断旧失败是否仍适用于当前 runtime |
| `runtime_freshness.visibility` | 系统上下文投影层使用，agent 可见的是摘要，不需要理解内部 hash |

### 3.3 Agent 上下文投影 TaskObservationProjection

投喂给 agent 的不再是裸 `observations`，而是：

```json
{
  "current_facts": [],
  "artifact_evidence": [],
  "active_failures": [],
  "historical_failures": [],
  "repair_focus": [],
  "open_questions": [],
  "last_action_receipts": []
}
```

投影规则：

| 记录类型 | 进入 agent 上下文的方式 |
| --- | --- |
| 当前 runtime 下的成功工具结果 | `current_facts` + `artifact_evidence` |
| 当前 runtime 下的可恢复失败 | `active_failures` + `repair_focus` |
| 当前 runtime 下的不可恢复失败 | `active_failures`，允许 agent block 或 ask_user |
| 旧 runtime/config 下的失败 | `historical_failures`，明确标注“仅供背景，不代表当前不可用” |
| completion validator 失败 | `repair_focus`，说明缺少哪些合同证据 |
| operation gate deny | `active_failures`，因为权限门禁仍是当前边界，除非权限配置已变化 |

### 3.4 记忆与上下文子 agent 的位置

记忆子 agent 和上下文压缩 agent 应接入在 projection 之后，而不是替代 freshness 裁决：

```text
ToolObservationLedger + TaskObservationProjection
-> context_compactor_agent 可压缩长历史
-> memory_search_agent 可检索相关历史经验
-> memory_system_agent 可在任务结束后维护长期记忆候选
-> 主 agent 接收 projection + summaries
```

允许子 agent 产出：

```text
长历史摘要
已尝试方案摘要
用户偏好和项目背景
历史失败模式归纳
恢复建议
```

不允许子 agent 产出并直接覆盖：

```text
当前工具是否授权
旧失败是否仍代表当前不可用
artifact 是否真实存在
operation gate 是否放行
TaskRun 是否完成
```

原因是这些属于系统协议事实，必须稳定、可复现、可审计。子 agent 的输出可以作为 `memory_summary` 或 `context_summary` 进入 `execution_state`，但必须被系统 freshness / permission / artifact verification 包裹。

## 4. 失败记录有效性规则

禁止用关键词过滤失败。有效性只能来自结构字段。

### 4.1 成功记录

成功记录满足任一条件：

```text
payload.result_envelope.status == "ok"
payload.structured_payload.tool_result.status == "ok"
payload.result JSON 中 ok == true
observation.error 为空且存在 artifact_refs / result / stdout / file receipt
```

成功记录可以作为当前事实复用，但 artifact 必须重新验证文件是否存在。

### 4.2 当前失败

失败记录满足任一条件：

```text
observation_type == "executor_error"
observation.error 非空
payload.result_envelope.status == "error"
payload.structured_payload.tool_result.status == "error"
payload.result JSON 中 ok == false
operation_gate.allowed == false
```

如果失败的 `runtime_fingerprint` 与当前 fingerprint 匹配，则它是当前失败：

```text
validity.visibility = active
reuse_as_fact = false
reuse_as_repair_context = true
```

agent 应该看到它，并据此修参数、换路径、重试、请求用户或 block。

### 4.3 过期失败

如果失败记录对应的执行环境已经变化，则它必须降级：

```text
tool config changed
tool registry changed
sandbox policy changed
permission profile changed
model provider/model changed and failure origin is model_runtime
backend/system config changed and failure origin is tool_provider/config
```

降级后的记录：

```text
validity.visibility = historical
reuse_as_fact = false
reuse_as_repair_context = false
reason = superseded_by_runtime_change
```

agent 可见摘要应该写成：

```text
历史失败：image_generate 曾在旧工具配置下失败；当前 runtime 已重新装配，不把该失败视为当前不可用证据。
```

而不是：

```text
image_generate 不可用。
```

### 4.4 Completion validator 失败

合同验收失败不是普通工具失败。它代表系统验收缺口，必须进入 `repair_focus`：

```json
{
  "kind": "completion_repair",
  "missing": ["required_artifacts"],
  "instruction": "继续创建或验证缺失产物，不能 final answer。"
}
```

这类失败即使跨 runtime 也不能简单丢弃，因为合同没有变化时，缺口仍有效。

## 5. Runtime Fingerprint 设计

每次 `execute_task_run` 重新装配 runtime 后，生成当前 fingerprint：

```json
{
  "runtime_assembly_id": "rtasm:...",
  "agent_profile_id": "agent:0",
  "runtime_mode": "professional",
  "task_environment_id": "env.development.workspace",
  "tool_registry_hash": "...",
  "tool_config_hash": "...",
  "sandbox_policy_hash": "...",
  "permission_policy_hash": "...",
  "backend_config_hash": "..."
}
```

最小实现要求：

| hash | 输入 |
| --- | --- |
| `tool_registry_hash` | available tool names + operation ids + tool definitions version |
| `tool_config_hash` | 与工具执行相关的系统配置，不包含密钥明文 |
| `sandbox_policy_hash` | sandbox root、write scopes、artifact root |
| `permission_policy_hash` | runtime profile permission policy |
| `backend_config_hash` | image/base_url/model 等非敏感配置 |

安全要求：

```text
不能把 API key、token、secret 放进 observation 或 runtime packet。
hash 输入可包含“是否存在 key”，但不能包含 key 原文。
```

## 6. Agent 可见提示设计

TaskRun 执行 prompt 需要从“裸 observations”升级为“当前执行状态包”。

当前系统提示可以保留核心身份：

```text
你是正式 TaskRun 的执行 agent。你已经不在普通对话轮次中，而是在执行一个已建立合同的长任务。
```

需要补充的高质量控制要求：

```text
系统会给你 execution_state，其中 current_facts 是当前可依赖事实，
artifact_evidence 是已经验证存在或已记录的产物证据，
active_failures 是当前 runtime 下仍然有效的失败，
historical_failures 是历史失败，只能作为背景，不能视为当前工具不可用。

当 active_failures 存在时，你需要判断是修正参数、换工具、重试、请求用户，还是明确 block。
当 historical_failures 存在时，你不能仅凭历史失败放弃当前工具；如果当前工具仍在 available_tools 中，应该按当前合同重新判断是否需要尝试。
完成前必须检查 repair_focus 和合同验收条件。只在真实产物和验证证据满足时 respond。
```

注意：这不是开发说明，而是给 agent 的任务执行行为边界。它告诉 agent 如何理解系统提供的运行时事实。

## 7. 文件级实施计划

### 7.0 `backend/runtime/memory/tool_observation_ledger.py`

扩展现有 `ToolObservationRecord`，不要新增平行账本类型：

```text
runtime_freshness: dict[str, Any]
structured_error: dict[str, Any]
```

`build_tool_observation_record()` 增加可选参数：

```python
runtime_fingerprint: dict[str, Any] | None = None
structured_error: dict[str, Any] | None = None
freshness: dict[str, Any] | None = None
```

约束：

```text
原有 read/write/verification/delegation evidence 逻辑继续归 ToolObservationLedger。
freshness 只表达这条记录相对当前 runtime 的有效性。
不要让 ledger 推断 agent 下一步行为。
```

### 7.1 `backend/harness/loop/task_executor.py`

新增或重写以下函数：

```text
_current_runtime_fingerprint(runtime_assembly, runtime_host, query_runtime)
_tool_record_from_observation(observation, current_fingerprint)
_classify_record_freshness(record, current_fingerprint)
_build_execution_state_projection(records)
_observations_for_packet(runtime_host, task_run_id, current_fingerprint)
```

替换：

```text
_reusable_observations()
```

目标行为：

```text
原始 observation 全部从 event_log 读取。
每条 observation 通过 ToolObservationLedger 规范化，再计算 freshness。
成功事实和当前失败都可以进入投影。
过期失败只进入 historical_failures。
artifact refs 只从成功事实和验证过的产物记录提取。
可选接入 context_compactor_agent / memory_search_agent 的摘要，但摘要不得覆盖系统 freshness。
```

`execute_task_run` 中应从：

```python
observations = _reusable_observations(runtime_host, task_run.task_run_id)
artifact_refs = _artifact_refs_from_observations(observations)
```

改为：

```python
observation_context = _observations_for_packet(...)
observations = observation_context["packet_observations"]
execution_state = observation_context["execution_state"]
artifact_refs = observation_context["artifact_refs"]
```

其中 `packet_observations` 应逐步收敛为精简后的 records，不再把所有 raw event 原样塞入模型。

### 7.2 `backend/harness/runtime/compiler.py`

`compile_task_execution_packet` 增加参数：

```python
execution_state: dict[str, Any] | None = None
```

`user_payload` 从：

```json
{
  "observations": []
}
```

升级为：

```json
{
  "execution_state": {},
  "observations": []
}
```

保留 `observations` 是为了兼容当前 packet schema 的内部消费，但 agent 主要依据 `execution_state`。

这里的兼容不是保留旧链路，而是同一新结构的过渡字段。完成后可以进一步删除裸 observations。

`execution_state` 允许包含子 agent 生成的摘要，但必须显式分区：

```json
{
  "system_projection": {},
  "memory_summary": {},
  "context_summary": {}
}
```

`system_projection` 是权威边界；`memory_summary` 和 `context_summary` 只能作为参考上下文。

### 7.3 `backend/runtime/tool_runtime/tool_executor.py`

确保工具执行结果 envelope 至少包含：

```json
{
  "status": "ok | error",
  "tool_name": "...",
  "operation_id": "...",
  "artifact_refs": [],
  "error": {
    "code": "",
    "message": "",
    "retryable": true
  }
}
```

图片工具失败时必须保留结构化 origin：

```text
tool_provider
tool_config
upstream_provider
network
validation
```

这样恢复层不需要用错误文案猜测。

### 7.4 `backend/runtime/context_management/tool_use_summary.py`

保留为摘要层，不让它承担 freshness 裁决。

需要调整：

```text
优先读取 ToolObservationRecord / ToolResultEnvelope 的结构化 status。
如果只有 legacy text，summary 可以标记 low_confidence。
不要通过 error/failed/失败 关键词决定系统有效性。
```

### 7.5 `context_compactor_agent` / `memory_search_agent`

短期实现不强制每步都调用子 agent。成熟策略应是按 context pressure 和 task duration 触发：

```text
history token 压力高
observation 数量超过阈值
TaskRun 被恢复
同类失败多次出现
用户要求参考历史记忆
```

触发后输出写入：

```text
execution_state.context_summary
execution_state.memory_summary
```

这些摘要不得修改：

```text
system_projection.active_failures
system_projection.historical_failures
system_projection.artifact_evidence
system_projection.permission_boundary
```

### 7.6 `backend/tests/query_runtime_runtime_loop_regression.py`

新增回归：

1. 旧 runtime 下失败的 `image_generate` observation 不进入 `active_failures`。
2. 旧失败进入 `historical_failures`，且标记 `reuse_as_fact=false`。
3. 当前 runtime 下失败的 tool observation 进入 `active_failures`。
4. 成功 artifact observation 进入 `artifact_evidence`，并参与 completion verification。
5. completion validator failure 进入 `repair_focus`，不得被 runtime 变化丢弃。

### 7.7 `backend/tests/sandbox_tool_runtime_regression.py`

新增或调整：

1. image tool envelope 失败时有结构化 `status=error`。
2. image tool 成功时 artifact refs 可被 TaskRun artifact resolver 识别。
3. backend `.env` 和 config root 不再被 sandbox root 覆盖。

### 7.8 `backend/tests/tool_observation_ledger_regression.py`

新增：

```text
ToolObservationRecord 保留原有 evidence 能力。
runtime_freshness 不改变 has_read / has_write / has_verification 的判断。
structured_error 不依赖错误文案关键词。
legacy text 只能产生低置信 debug_hints，不允许成为 freshness 的权威来源。
```

## 8. 不实施的方案

### 8.1 不把所有历史 observation 原样塞给 agent

原因：

```text
agent 会把旧失败当作当前现实，尤其在系统修复后产生错误 block。
上下文会膨胀，长任务越跑越脏。
旧失败、当前失败、验收失败的语义不同，不能混在同一列表里。
```

### 8.2 不简单丢弃所有失败 observation

原因：

```text
agent 需要失败证据来修复参数、路径、权限、工具选择。
长期任务的自我修正能力依赖失败上下文。
丢弃失败会让 agent 重复踩坑。
```

### 8.3 不用关键词识别过期失败

禁止：

```python
if "Tool choice" in error:
    stale = True
```

原因：

```text
这会重新引入启发式分类。
错误文案来自 provider，不能作为控制协议。
成熟系统必须用结构字段和 runtime fingerprint 判断。
```

### 8.4 不由系统替 agent 决定重试

系统可以标注：

```text
当前失败是否仍有效
是否 retryable
是否由权限门禁导致
是否已有替代工具
```

系统不应该直接决定：

```text
下一步一定重试 image_generate
下一步一定改用某工具
下一步直接 block
```

这些属于 agent 的执行判断。

## 9. 验收标准

实现后必须满足：

1. 长任务续跑时，旧配置导致的失败不会再让 agent 误判当前工具不可用。
2. 当前 runtime 下真实失败会进入 agent 上下文，agent 能据此修复或 block。
3. 系统修复工具配置后，继续执行 TaskRun 不需要清空整个历史账本。
4. artifact refs 只来自真实工具结果、真实文件或验收记录。
5. `runtime_invocation_packet_compiled` 事件中能看到 `execution_state`。
6. 用户监控台显示的是步骤摘要和当前状态，不暴露内部 task id 作为主要内容。
7. 回归测试覆盖成功、当前失败、过期失败、验收失败四类 observation。

## 10. 推荐实施顺序

```text
1. 扩展 ToolObservationRecord，补 runtime_freshness / structured_error。
2. 在 task_executor.py 内实现 fingerprint、record freshness、TaskObservationProjection。
3. 修改 compiler.py 支持 execution_state，并把 system_projection 与 memory/context summary 分区。
4. 调整 task_execution prompt，让 agent 正确理解 active/historical failure。
5. 补充结构化 tool envelope 错误字段。
6. 接入可选 context_compactor_agent / memory_search_agent 摘要触发点，但不让子 agent 参与 freshness 裁决。
7. 写 focused regression。
8. 重启 8003 后端。
9. 对现有五层地下塔 TaskRun 续跑，验证 agent 不再被旧 image_generate 失败误导。
```

## 11. 当前长任务的预期修复效果

对当前五层地下塔任务，修复后的上下文应该类似：

```json
{
  "current_facts": [
    "已有 HTML / 文档产物记录",
    "任务合同要求真实 PNG 美术资源"
  ],
  "artifact_evidence": [
    {
      "path": "frontend/public/souls/generated/...",
      "exists": true,
      "kind": "image"
    }
  ],
  "active_failures": [],
  "historical_failures": [
    {
      "tool_name": "image_generate",
      "reason": "superseded_by_runtime_change",
      "summary": "旧工具配置下 image_generate 曾失败；当前 runtime 已重新装配。"
    }
  ],
  "repair_focus": [
    "继续生成缺失 PNG 资产",
    "验证 index.html 真实加载这些资产",
    "不能用 SVG 或纯文档替代游戏交付"
  ]
}
```

agent 因此应该继续执行，而不是因为历史失败直接放弃。
