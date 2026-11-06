# mythical-age 旧残留与冗余审查

审查对象：`D:\mythical-age\Mythical-Age--\backend`（1160 个 .py / 36.9 万行）
审查方式：静态扫描 + 关键文件实读。**未执行任何代码**，凡标注"未验证"处均未打开细读。
每条给出 `文件:行号`，可直接跳转核对。

---

## P0 ── 同一概念存在第二真相源（会埋 bug）

### P0-1 任务运行状态常量在两处定义，且 `FAILED` 口径不一致

| 位置 | 定义 |
|---|---|
| `harness/task_run_status.py:7-52` | `CANONICAL_TASK_RUN_STATUSES`、`COMPLETED={completed}`、`FAILED={failed}`、`STOPPED={aborted}`、`TERMINAL_TASK_RUN_STATUSES`、`STOP_CONTROL_STATES`、`GATEWAY_BACKED_CONTROL_REQUEST_STATES` |
| `harness/runtime/run_monitor/lifecycle.py:3-11` | `RUNNING`、`WAITING`、`BLOCKED`、**`FAILED={failed, aborted}`**、`COMPLETED`、`TERMINAL`、`KNOWN_TASK_RUN_STATUSES` |

`COMPLETED_TASK_RUN_STATUSES` / `FAILED_TASK_RUN_STATUSES` / `TERMINAL_TASK_RUN_STATUSES` 三个同名常量在两处各自定义。
**`FAILED` 一处只含 `failed`，另一处含 `failed` + `aborted`** —— 这会直接导致"某个 run 是否算失败"的判定在两处不同。
→ 建议：状态集合收敛到 `harness/task_run_status.py` 一处，`run_monitor/lifecycle.py` 改为导入。

### P0-2 两套 TaskRunContract 并存

| 契约 | 位置 | 状态 |
|---|---|---|
| `TaskContract`（45 字段） | `task_system/contracts/contracts.py` | 仅由 `services/assembly_builder.py:148` 与 `assembly/contract_issuer.py:84` 生产；`harness/**` 无一处 import |
| `TaskRunContract` | `harness/loop/task_lifecycle.py:12` | 运行时实际使用，`runtime_facade.py` 全程以它签名 |

而且运行时**仍在防御旧的契约字段**：
- `harness/loop/model_action_protocol.py:602` `_legacy_task_run_contract_seed_errors`
- `:543` / `:605-611` 产出 `legacy_task_run_contract_field_not_allowed:*`
- `:502` `_REQUEST_TASK_RUN_LEGACY_SEED_TEXT_FIELDS = ("user_visible_goal", "task_run_goal")`

模型侧提示词也已声明"只提交紧凑 TaskStartIntent，运行时会生成内部 TaskRunContract"（`single_agent_turn.py:5389` / `:5694`）。
→ 既然对外契约已改，`TaskContract`（45 字段那套）与旧字段拒绝逻辑需要明确处置：要么接入主链，要么删除。

### P0-3 幂等键生成有六套实现

| 位置 | 用途 |
|---|---|
| `graph_system/context_materializer.py:485` | `_work_order_idempotency_key` |
| `runtime/shared/execution_record.py:372` | `build_idempotency_token` |
| `runtime/tool_runtime/tool_invocation_control.py:391` | `build_tool_invocation_idempotency_key` |
| `runtime/tool_runtime/tool_result_envelope.py:242` | `build_tool_result_idempotency_key` |
| `task_system/graph_instances/decision_models.py:169` | `decision_idempotency_key` |
| `runtime/trace/service.py:235` | `_scoped_idempotency_key` |

六处的**参数规范化规则与哈希口径各自维护**。工具调用/工具结果/执行记录三处尤其危险——同一个操作可能因入口不同算出不同键。
→ 建议：抽出一个规范化 + 哈希的公共底座，六处只声明各自的键成分。

---

## P1 ── 已清理项的防御残留（违反项目自己的 AGENTS.md）

`AGENTS.md` 原文："默认清理无用旧代码…**不要防御在程序内已经被清理的东西**或者被修复的 bug。"

### P1-1 三类"已移除的健康配置"仍被识别与排除

```
agent_system/profiles/runtime_profile_registry.py:47    _is_removed_health_runtime_profile
task_system/registry/flow_registry.py:82               _is_removed_health_task_config
task_system/registry/workflow_registry.py:15           _is_removed_health_workflow
```
调用点：`runtime_profile_registry.py:1119`、`flow_registry.py:305/312/324/337`、`workflow_registry.py:107`
还有 `harness/runtime/run_monitor/lifecycle.py` 之外的 `_is_removed_health_*` 引用（未逐一展开）。

### P1-2 已移除的模板协议仍被构造

```
api/task_system.py:789                      "template_protocol_removed": True
task_system/planning/execution_recipe_builder.py:27  同上
task_system/services/registry_overview.py:302         _removed_template_protocol_matrix()
```
**一个已移除的东西还在生成"移除矩阵"**，属于纯噪声。

### P1-3 旧执行器类型仍在合法集合里

```
graph_system/node_adapter_models.py:35   LEGACY_EXECUTOR_TYPES = {"agent","resource","review_gate","tool"}
graph_system/models.py:839               supported = set(LEGACY_EXECUTOR_TYPES) | {8 种新类型}
```
图校验同时接受**新旧两代执行器类型**。其中 `"tool"` 对应的执行器本身未接线（见 P2-2）。

---

## P2 ── 死链路与未接线

### P2-1 弃用的 continuation selector 仍挂在主流程上

`harness/continuation/selector.py`：`select_session_continuation` **恒返回 `available: False`**，理由固定为 `legacy_task_run_continuation_removed`。

但它仍被**四处调用**：
```
api/chat.py:370
api/chat.py:459
api/chat.py:2135
harness/entrypoint/runtime_facade.py:678
```
而且函数体内**仍在真实读取 host**（`_context_recovery_status_from_host`）来为必然为假的结果做计算。
→ 要么删除该函数与四处调用，要么保留但去掉那次 host 读取。

### P2-2 工具型图节点执行器未接线

```
graph_system/work_order_executor.py:79   reason="graph_tool_node_executor_not_connected"
```
`work_kind == "tool"` 直接返回"未接线"。**但 `"tool"` 仍在 LEGACY_EXECUTOR_TYPES 里合法**（P1-3）——校验放行、执行拒绝。

### P2-3 工具控制面两条路径的调用方派发未接线

```
runtime/tool_runtime/tool_control_plane.py:179   "stage": "caller_dispatch_not_connected"
runtime/tool_runtime/tool_control_plane.py:465   同上
```

### P2-4 Office 写补丁未接线

```
capability_system/capabilities/document_processing/projections/office_projection.py:17
    unsupported_actions.append("write_patch_execution_not_connected")
```

### P2-5 `ToolRepetitionGuard` 是死代码

定义在 `runtime/shared/tool_repetition_guard.py:9`，**全库唯一引用是导出表** `runtime/__init__.py:36`，无任何调用点。
注意：项目简历文档 `docs/MYTHICAL_AGE_INTERVIEW_RESUME_QA.md` 把"重复调用防护"列为已实现能力（简历要点 3）——**与代码不符**。

---

## P3 ── 迁移期身份双轨

### P3-1 `legacy_task_run_id` 迁移轴：40 处，横跨 8 个文件

```
api/harness.py
api/runtime_logs.py
graph_system/runtime.py
harness/runtime/run_monitor/actions.py
harness/runtime/run_monitor/projector.py
harness/runtime/run_monitor/service.py
runtime/memory/state_index.py
runtime/shared/models.py
```

`runtime/shared/models.py:121-134` 的 `RuntimeAnchor` 注释原文：

> RuntimeAnchor is the migration target for runtime identity. **During the migration, `legacy_task_run_id` remains the event-log and retention scope**, but new projections can name the runtime unit without treating TaskRun as task truth.

含义：**运行身份有新旧两种，事件日志与保留策略的权威仍挂在旧轴上**（`legacy_task_run_id` 字段，`:134`；`:98` `legacy_task_run_id=task_run_id`）。
→ 这是整个工作区"大规模重构未收敛"的根节点。收敛顺序上它应该排第一。

---

## P4 ── 文档与实现不一致

### P4-1 README 声称的提示词引擎层不存在

`README.md:161-162` 写：

> **Prompting（`prompting/`）——提示词引擎层：** Prompt 构建器（builder.py）、缓存（prompt_cache.py）、策略原型（strategy_prototypes.py）、专业 Profile（professional_profiles.py）

实际：**`backend/prompting/` 目录不存在**。只有 `prompt_library/` 与 `prompt_composition/`；后者仅 3 个文件（`__init__.py` / `assembly_plan.py` / `context_envelope.py`），没有 materializer、渲染器、运行时槽位。

### P4-2 `knowledge_system/services/` 是空包

README 称"服务（services/）：知识检索服务封装"。实际该目录只有 `__init__.py`（1 行 docstring）。
检索实现实际位于 `capability_system/capabilities/retrieval/`。

### P4-3 其余空壳包

```
capability_system/capabilities/__init__.py      0 行（子目录有内容，包本身为空）
knowledge_system/evidence/__init__.py           1 行
knowledge_system/models/__init__.py             1 行
task_system/editor/__init__.py                  1 行
context_system/packaging/__init__.py            2 行
```

---

## P5 ── 命名易混（非冗余，但会持续误导维护者）

| 易混对 | 说明 |
|---|---|
| `graph_system/loop.py`（4014 行） vs `graph_system/loop_engine.py`（106 行） | 主循环 vs 节点循环变量解析，名字近乎同名 |
| `graph_system/extensions.py`（130 行） vs `bootstrap/graph_extensions.py`（34 行） | 两处都叫 graph extensions |
| `harness/runtime/`（宿主实现） vs 顶层 `runtime/`（运行时系统） | 同名不同物，跨包引用极易看错 |
| `runtime/memory/`（state_index） vs `memory_system/`（五层记忆） | 两个 memory |
| `task_system/graphs/`（图定义） vs `graph_system/`（图执行） | 两个 graph |
| `harness/task_run_status.py` vs `runtime/shared/models.py::TaskRunStatus` | 两个 TaskRunStatus |
| 监控三处：`harness/runtime/run_monitor/`（12 文件） + `api/harness_run_monitor.py` + `api/runtime_logs.py`/`runtime_trace.py` | 三处投影同一运行事实 |

---

## 建议的收敛顺序

1. **P3-1 运行身份单轴** —— 决定 `RuntimeAnchor` 与 `legacy_task_run_id` 谁权威，其余问题都在它下游。
2. **P0-1 状态常量合一** + **P0-3 幂等底座合一** —— 改动小、收益直接，且能立刻消除口径不一致。
3. **P0-2 契约二选一** —— `TaskContract` 接入主链或删除，同时清掉旧字段拒绝逻辑。
4. **P1 全部清掉** —— 已移除项不留识别逻辑，符合项目自己的 AGENTS.md。
5. **P2 死链路** —— selector 与 guard 二选一处置；未接线的四处要么接上要么标注为已知未完成。
6. **P4 文档对齐** —— README 的 `prompting/` 段落与 `knowledge_system/services/` 描述按实现改写。

> 未验证项：`run_monitor` 的 12 个文件未逐一细读；`project_network_tasks/` 的三条运行链路未展开；前端是否消费已废弃字段未查。
