# Graph Runtime Config Authority Refactor Plan

## 背景

当前图任务运行实例和图配置发布版本存在错误的权力绑定：

- `GraphRun` 持久化 `config_id` / `config_hash`。
- `GraphLoopState` checkpoint 持久化同一组 `config_id` / `config_hash`。
- API scope 校验要求请求传入的 `GraphHarnessConfig` 与 `GraphRun.config_id` 完全一致。
- `GraphResumeService`、`GraphRunRunner`、`GraphNodeWorkOrderExecutor` 继续用同一组 id/hash 校验运行、checkpoint、work order。

这导致只修改节点执行参数、prompt 装配、模型组、缓存策略或局部工具权限时，旧 run 无法继续运行。实际权力边界应当是：

- 图结构身份决定 checkpoint 能否被同一拓扑恢复。
- 运行设置决定本次执行如何调用模型、装配 prompt、分配 API、应用缓存策略。
- 图运行实例拥有自己的可变运行设置，不能被配置发布版本替代。

## 当前权力链

| 模块 | 当前角色 | 问题 |
| --- | --- | --- |
| `backend/api/orchestration.py` | 请求 scope 校验 | 把 `GraphRun.config_id` 与请求配置 id 强绑定，阻止旧 run 使用等价结构的新执行配置。 |
| `backend/harness/graph/runtime.py` | 创建 graph run | 把完整 `GraphHarnessConfig.content_hash` 固化进 run/checkpoint。 |
| `backend/harness/graph/loop.py` | checkpoint 与调度状态权威 | `GraphLoopState.config_hash` 代表完整配置 hash，缺少独立结构 hash。 |
| `backend/harness/graph/resume.py` | 恢复权威 | 用完整配置 id/hash 判断可恢复性。 |
| `backend/harness/graph/runner.py` | 执行循环权威 | 用完整配置 id/hash 判断 state/work_order 是否属于当前运行。 |
| `backend/harness/graph/work_order_executor.py` | 节点执行权威 | 校验 work order config id，而不是校验 graph run + node identity + structural identity。 |
| `backend/harness/graph/model_overrides.py` | 运行设置合并 | 已有模型覆盖能力，但只覆盖模型字段，不能承载结构/执行配置分界。 |

## 目标权力链

```text
PublishedGraphConfig
-> GraphStructureIdentity
-> GraphRunInstance
-> GraphRunRuntimeSettings
-> NodeWorkOrder
-> RuntimeOverrides
-> AgentExecution
```

职责边界：

- `PublishedGraphConfig`：提供完整配置内容，包括拓扑、节点契约、默认执行配置。
- `GraphStructureIdentity`：只描述可恢复拓扑和节点/边/资源结构，不包含模型、prompt 文案、缓存策略、credential、token budget 等可变执行项。
- `GraphRunInstance`：绑定一次图运行、session scope、project scope、结构身份。
- `GraphRunRuntimeSettings`：保存可变执行配置，支持 patch。
- `NodeWorkOrder`：绑定 graph run、node id、结构身份和当次装配结果。
- `RuntimeOverrides`：临时覆盖，优先级高于持久 settings。
- `AgentExecution`：只执行收到的 work order，不重新决定配置来源。

## 设计方案

### 1. 引入结构身份

在 `GraphHarnessConfig` 增加结构身份计算函数：

- `structural_payload()`
- `expected_structural_hash()`

结构 payload 包含：

- `graph_id`
- 节点 id、node type、executor type、resource/loop 结构标识
- 边 id、source、target、edge type、semantic role、scheduler role
- 会影响 checkpoint 恢复和节点流转的 loop/resource 控制字段

结构 payload 不包含：

- 模型配置
- prompt 文案
- prompt cache 配置
- API credential / provider
- token/timeout/retry 预算
- agent profile 的可变执行描述
- 节点局部工具权限中不改变图拓扑的执行工具开关

### 2. 扩展运行状态字段

在 `GraphRun`、`GraphLoopState`、`GraphRuntimeEnvelope` 中新增：

- `structure_hash`
- `structure_version`，默认 `graph_structure.v1`
- `config_snapshot_id`
- `config_snapshot_hash`

保留原 `config_id` / `config_hash` 作为发布配置快照引用，不再作为 resume/run 的唯一许可边界。

### 3. 修改校验权力

API 和 runtime 校验改为：

- `graph_id` 必须一致。
- `task_environment_id` / `project_id` scope 必须一致。
- `structure_hash` 必须一致，或在旧 checkpoint 缺失结构 hash 时由旧 `config_hash` 做一次性旧状态投影。
- `config_id` 不再要求一致。
- `content_hash` 不再用于运行恢复许可，只用于配置快照追踪和审计。

配置解析规则：

- 请求仍可显式传入 `graph_harness_config_id`，但它表示“本次要使用的执行配置快照”，不再表示 run 归属权。
- 如果未传入配置，API 可以按 `graph_id + task_environment_id + published` 选择最新兼容配置；兼容条件必须由 `structure_hash` 判断。
- 如果传入配置与 run 的 `graph_id` 或结构身份不一致，必须拒绝。
- `GraphHarnessConfig.content_hash` 自身仍必须通过 `expected_content_hash()` 校验，防止损坏或未正确发布的配置被执行；只是它不再与旧 run 绑定。

### 4. 运行设置 patch 成为正式能力

保留并强化 `runtime_settings_patch`：

- 持久设置存入 `GraphLoopState.diagnostics.runtime_settings`。
- 执行优先级固定为：
  `temporary runtime_overrides > graph_run runtime_settings > graph config defaults`
- 补充支持按节点/角色/agent 分组覆盖：
  - `model_overrides`
  - `prompt_assembly_overrides`
  - `tool_policy_overrides`
  - `cache_policy_overrides`
  - `node_runtime_policy_overrides`

禁止 raw secret，只允许 `credential_ref`。

授权边界规则：

- `runtime_settings_patch` 只能收窄或选择已经被图结构/节点契约允许的能力，不能凭空扩大节点能力。
- `tool_policy_overrides` 必须有静态 ceiling：最终 allowed operations 只能是 `GraphConfig/NodeConfig/AgentProfile` 共同允许集合的子集。
- `subagent_policy`、`allowed_subagent_ids`、写文件权限、外部网络权限属于授权边界；如果 patch 需要扩大这些能力，必须拒绝或要求重新发布结构兼容配置中的授权 ceiling。
- `prompt_assembly_overrides` 可以改变 prompt cache 分段和装配顺序，但不能移除系统级职责、验收、权限、输出契约片段。

### 5. Work order 绑定结构身份

`GraphNodeWorkOrder` 增加：

- `structure_hash`
- `config_snapshot_id`
- `config_snapshot_hash`

Runner 只要求：

- work order 属于当前 graph run
- node id 合法
- structure hash 与当前 state 一致

不再要求 work order config id/hash 与当前传入 config 完全相同。

旧 work order 处理：

- 仍在运行中的旧 work order 若缺少 `structure_hash`，恢复时不能直接执行；需要重新 dispatch 生成新 work order。
- `active_work_orders` 在配置执行快照变化后应被断开并回到对应节点 ready 状态，避免旧 work order 携带旧 prompt/runtime_profile 继续跑。
- 已完成 work order/result 只作为历史和上游输入保留，不作为新执行配置的来源。

### 6. 从指定节点重排队

新增受控 requeue 能力：

- 输入：`graph_run_id`、`start_node_ids`、可选 `runtime_settings_patch`
- 行为：reset 起点及其下游非资源节点
- 保留：上游已完成结果、flow packet、记忆/资源节点结果
- 清理：起点及下游 result_index、active_work_orders、失败边状态

这用于“从大纲后重跑 1-10 章正文”，不需要新建 graph run。

API 入口：

- 新增 `POST /orchestration/harness/graph-runs/{graph_run_id}/requeue-nodes`。
- 请求字段：`graph_harness_config_id`、`session_scope`、`start_node_ids`、`runtime_settings_patch`、`reset_downstream`。
- 默认只 reset 起点及下游非资源节点。
- 返回新 checkpoint、重排队节点、被清理结果、保留上游摘要。

### 7. 运行审计同步

以下字段需要同步到 task run、graph run、checkpoint 和 monitor：

- `graph_structure_hash`
- `graph_structure_version`
- `config_snapshot_id`
- `config_snapshot_hash`
- `runtime_settings_revision`
- `runtime_settings_patch_history`

审计规则：

- `config_id` / `config_hash` 字段短期保留为旧字段，但语义改名为 snapshot 引用；公共 monitor 应明确显示 `structure_hash` 才是恢复许可依据。
- 不允许通过直接改 runtime object 迁移配置。所有配置切换必须记录为 runtime settings patch 或 compatible config snapshot switch event。

## 实施文件

预计修改：

- `backend/harness/graph/models.py`
- `backend/harness/graph/runtime.py`
- `backend/harness/graph/loop.py`
- `backend/harness/graph/resume.py`
- `backend/harness/graph/runner.py`
- `backend/harness/graph/work_order_executor.py`
- `backend/harness/graph/model_overrides.py`
- `backend/harness/graph/context_materializer.py`
- `backend/api/orchestration.py`
- `backend/tests/graph_model_overrides_regression.py`
- 新增测试：`backend/tests/graph_runtime_config_authority_regression.py`

不修改：

- 单 agent 执行主循环。
- 现有 agent prompt 语义。
- 当前图拓扑本体。

## 测试计划

聚焦测试：

```powershell
python -m pytest backend/tests/graph_runtime_config_authority_regression.py backend/tests/graph_model_overrides_regression.py -q
```

已有写作图回归：

```powershell
python -m pytest backend/tests/writing_modular_graph_self_repair_regression.py backend/tests/writing_chapter_loop_progress_regression.py -q
```

真实运行验证：

1. 发布当前写作图配置。
2. 对旧 graph run 应用 runtime settings patch。
3. 从 `graph_module.chapter_cycle::chapter_draft` 重排队。
4. 调用固定后端 `http://127.0.0.1:8003` 的 `run-until-idle`。
5. 检查 work order 是否使用新 settings，且没有因 config id/hash mismatch 中断。
6. 检查 1-10 章产物字数和质量门。

## 风险和边界

- 结构 hash 定义必须保守，宁可把会影响恢复语义的字段纳入结构身份，也不要让不兼容拓扑被误续跑。
- 旧 checkpoint 缺少结构 hash，需要一次性投影逻辑；投影只用于恢复旧 run，不作为长期兼容分支。
- prompt 文案是否属于结构身份：默认不属于。prompt 改动影响执行质量，但不影响 checkpoint 拓扑恢复。
- 工具权限是否属于结构身份：只有改变节点可执行能力边界且影响 work order 形态时才纳入结构身份；普通运行策略覆盖走 runtime settings。

## 完成标准

- 调模型、API 组、prompt cache、节点执行策略不再要求新建 graph run。
- 旧 run 可以在结构一致的新配置下继续或从指定节点重跑。
- 不再通过手工改 `config_id` / `config_hash` 绕过运行。
- 测试覆盖 config 内容 hash 变化但 structure hash 不变时可续跑。
- 测试覆盖结构 hash 变化时明确拒绝续跑。
- 测试覆盖 runtime patch 不能扩大工具/子 agent/文件权限。
- 测试覆盖旧 active work order 在执行配置切换后被重新 dispatch，而不是继续用旧装配执行。
