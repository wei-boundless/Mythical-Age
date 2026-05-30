# GraphHarness 模型可见合同瘦身与权责分层优化方案

日期：2026-05-31

## 1. 问题结论

本次写作图实测中，`character_design` 节点实际耗时约 239 秒。它不是图循环死锁，也不是边契约错位，而是模型可见 prompt 过重：

- `runtime_invocation_packet_compiled` 外部化 payload 约 369KB。
- 模型消息段合计约 235KB。
- `Task execution stable contract` 单段约 81KB。
- `task_stable` 中，节点职责文本只有约 1.1KB，但 `graph_slot` 约 87KB，`acceptance_policy` 约 8KB。
- `character_design_round_001.md` 输出约 21KB、242 行，说明节点还被配置为大输出设计节点。

根因是 GraphHarness 的 runtime 合同和模型可见合同没有严格分层。当前实现把本应由 runtime 消费的节点、边、记忆、输出和恢复控制结构投影进了模型 prompt。虽然旧链路中的 `input_package` 已从模型可见路径移除，但新的 `graph_slot` 投影仍然携带过多 runtime-only 合同，导致模型上下文膨胀。

正确方向不是继续压缩自然语言 prompt，而是修复权责边界：

```text
GraphHarnessConfig / GraphRuntime / GraphLoop / WorkOrder
  保存完整合同、拓扑、状态、边协议、记忆协议、输出策略、恢复策略

RuntimeCompiler
  只把 agent 完成当前节点所需的最小语义合同投影给模型

Agent
  只理解角色、授权输入、输出要求、禁止事项、必要 loop 变量
```

## 2. 当前代码证据

### 2.1 运行路径

核心路径：

```text
GraphContextMaterializer
  -> GraphNodeWorkOrder.graph_slot
  -> query.runtime._graph_node_contract_from_work_order
  -> TaskRunContract.graph_slot
  -> RuntimeCompiler._task_contract_stable_payload
  -> _graph_slot_model_visible_projection
  -> model_messages
```

相关文件：

- `backend/harness/graph/context_materializer.py`
- `backend/query/runtime.py`
- `backend/harness/runtime/compiler.py`
- `backend/harness/graph/output_policy.py`
- `backend/harness/graph/models.py`

### 2.2 关键问题函数

`backend/harness/runtime/compiler.py` 中的 `_graph_slot_model_visible_projection()` 名义上是 model visible projection，但仍然投影了太多 runtime-only 内容：

- `node_contract`
- `edge_contracts`
- `memory_contract`
- `loop_contract`
- `output_contract`
- `visibility`

其中 `_graph_slot_node_contract_projection()` 继续携带：

- `input_contract`
- `output_contract.contract_bindings`
- `acceptance_policy`
- `node_identity.task_ref`

`_graph_slot_edge_contracts_projection()` 继续携带：

- `inbound_flow_packets`
- `inbound_edge_contexts`
- `outbound_edge_policies`

`_graph_slot_output_contract_projection()` 继续携带：

- `output_policy`
- `expected_result_contract`

这些结构不是 agent 语义执行所必需，属于 runtime 编排、校验、写入和恢复合同。

## 3. 权责审查

### 3.1 分层原则

图任务系统的合同应分为四类：

| 合同类别 | 权威层 | 是否进模型 | 说明 |
| --- | --- | --- | --- |
| 节点语义合同 | 节点配置 / 编辑器 | 是，瘦身后进入 | 角色、职责、边界、输出语义 |
| 边通信合同 | GraphRuntime / GraphLoop | 只进授权后的输入槽 | 边决定下游能看到上游什么，不把完整边协议交给模型 |
| 记忆读写合同 | GraphRuntime / MemoryRuntime | 只进实际记忆快照/摘要 | repository、collection、namespace、生命周期由 runtime 执行 |
| 运行控制合同 | GraphRuntime / GraphLoop / Executor | 否 | checkpoint、retry、resume、ack、idempotency 不进模型 |

### 3.2 当前错位

当前错位不是“合同太多”本身，而是“合同消费者错了”：

- 完整 `graph_slot` 应该给 runtime，不应该给模型。
- 完整 `memory_contract` 应该给记忆系统，不应该给模型。
- 完整 `edge_contracts` 应该给 loop 和 materializer，不应该给模型。
- 完整 `output_policy` 应该给 artifact materializer，不应该给模型。
- 模型只应该看到这些合同执行后的语义结果。

## 4. 无用或不应模型可见的合同清单

### 4.1 系统识别字段

这些字段只用于系统识别、幂等、追踪和恢复，不进入 prompt：

- `graph_identity`
- `graph_run_id`
- `root_task_run_id`
- `task_run_id`
- `config_id`
- `config_hash`
- `node_id` 的完整内部前缀
- `work_order_id`
- `slot_id`
- `checkpoint_ref`
- `state_refs.inbound_packet_refs`
- `state_refs.artifact_refs`
- `authority`
- `materializer_authority`
- `dispatch_event_id`
- `idempotency_key`

模型只需要自然语言形式的当前节点身份，例如：

```text
当前节点：人设与关系设计。
当前阶段：设计初始化。
```

### 4.2 运行控制合同

这些字段由 GraphLoop、runner、executor 消费，不进入 prompt：

- `runtime_controls`
- `retry_policy`
- `timeout_policy`
- `failure_policy`
- `resume_policy`
- `disconnect_policy`
- `post_node_gate_policy`
- `human_gate_policy`
- `execution_mode`
- `wait_policy`
- `join_policy`
- `scheduler_role`
- `ack_required`
- `ack_policy`
- `receipt_policy`
- `dispatch_context`
- `control_state`

模型不应该看到 “checkpoint / ack / retry / resume / work_order” 等内部机制，也不应该根据这些机制决定工作内容。

### 4.3 完整边协议

这些字段不直接进入模型：

- `inbound_flow_packets`
- `outbound_edge_policies`
- `edge_id`
- `source_node_id`
- `target_node_id`
- `payload_contract_id`
- `packet_contract_id`
- `delivery_policy`
- `projection_policy`
- `visibility_policy`
- `receipt_ref`
- `result_refs`
- `memory_refs` 的完整 runtime ref 列表

模型只看边协议执行后的授权输入槽：

```json
{
  "inputs": [
    {
      "slot": "上游交接包",
      "source": "世界观基准提交",
      "content": "..."
    },
    {
      "slot": "基准库",
      "source": "world_bible",
      "content": "..."
    }
  ]
}
```

边契约仍然存在，但它的作用是 runtime 授权和装配，不是直接向模型展示完整协议。

### 4.4 完整记忆协议

这些字段不进入模型：

- `namespace_id`
- `read_protocols`
- `write_protocols`
- `repository_node_id`
- `repository_id`
- `collection_specs`
- `lifecycle_policy`
- `write_owner_node_ids`
- `readable_by`
- `version_selector`
- `scope_id_source`
- `graph_task_memory_namespace` 的完整对象

模型只看：

- 本节点实际可见的记忆包名称。
- 记忆包摘要或授权内容。
- 哪些冻结事实不能改写。
- 哪些内容只是候选。

示例：

```text
可见记忆：
- 基准库/world_bible：已冻结世界观摘要。
- 基准库/forbidden_changes：不可改写项。

禁止：
- 不得改写已冻结世界观。
- 不得把候选角色写成已冻结事实。
```

### 4.5 输出和 artifact 写入策略

这些字段由 artifact materializer 消费，不进入模型：

- `artifact_policy`
- `target_environment_id`
- `target_repository_id`
- `target_collection_id`
- `root_policy`
- `subdir_template`
- `content_source`
- `fallback_to_full_content`
- `artifact_materialization_policy`
- `artifact_targets` 的完整 runtime 配置
- `output_policy` 的完整对象
- `expected_result_contract` 的 runtime 校验细节

模型只看：

```text
输出要求：
- 生成《角色设计候选》。
- 必须标明候选性质。
- 必须包含核心视角人物、关键关系人物、主要对抗者、关系网、情感回报设计。
```

文件路径可以以自然语言给出，但不需要完整 repository 配置：

```text
产物名：design/character_design_round_001.md
```

### 4.6 重复 prompt 字段

当前同一职责文本可能同时存在于：

- `prompt_contract.role_prompt`
- `user_visible_goal`
- `task_run_goal`
- `graph_slot.node_contract.prompt_contract`
- `input_package.agent_instruction`

模型只需要一份规范化后的 `node_prompt`。其它字段保留在 runtime 记录中，不进入模型消息。

目标：

```json
{
  "node_prompt": {
    "role": "...",
    "task": "...",
    "output": "...",
    "forbidden": [],
    "done": []
  }
}
```

### 4.7 工具表和操作策略

如果图节点只允许 `op.model_response`，不应展示完整工具表。

不进入模型：

- `available_tools` 全量列表
- 不可用工具说明
- denied operations 全量表
- permission policy 全量对象

模型只看：

```text
当前节点不能调用工具，只能基于授权输入生成输出。
```

工具调用未来也应当作为合同，但由 agent profile / tool permit / edge contract 控制，不应把全局工具目录交给无工具节点。

## 5. 目标模型可见合同

RuntimeCompiler 应生成一个新的瘦身结构，建议命名为：

```text
GraphNodeModelContext
```

模型可见结构只包含：

```json
{
  "node": {
    "title": "人设与关系设计",
    "role": "中文商业网文人设与关系设计师",
    "task": "...",
    "forbidden": [],
    "definition_of_done": []
  },
  "authorized_inputs": [
    {
      "slot": "上游交接包",
      "label": "世界观基准提交",
      "content": "..."
    }
  ],
  "memory": [
    {
      "label": "基准库/world_bible",
      "content": "...",
      "visibility": "read_only_frozen"
    }
  ],
  "loop": {
    "volume_index": 1,
    "chapter_index": 1,
    "batch_range": "001-010",
    "target_measure_units": 1000000,
    "unit_target_measure": 2000
  },
  "output": {
    "artifact_path": "design/character_design_round_001.md",
    "required_sections": [],
    "candidate_state": "model_output_candidate"
  },
  "constraints": [
    "不得改写已冻结世界观。",
    "不得把候选角色写成已冻结事实。"
  ]
}
```

## 6. 实施方案

### 阶段一：新增模型可见投影层

文件：

- `backend/harness/runtime/compiler.py`

动作：

1. 新增 `_graph_node_model_context_projection(graph_slot)`。
2. 将 `_task_contract_stable_payload()` 中的 graph 节点分支从 `graph_slot` 全量投影改为 `graph_node_context` 瘦身投影。
3. 保留完整 `graph_slot` 在 `TaskRunContract` 和 runtime object 中，供 runtime 使用。
4. 禁止 `acceptance_policy.contract_bindings`、`output_policy`、`memory_contract.read_protocols`、`outbound_edge_policies` 进入模型消息。

完成标准：

- 模型消息中不出现 `graph_identity`、`state_refs`、`runtime_controls`。
- 模型消息中不出现 `work_order_id`、`config_hash`、`checkpoint_ref`。
- 模型消息中不出现完整 `artifact_policy`、`memory_read_policy`、`memory_writeback_policy`。
- 角色类节点 stable contract 目标小于 20KB。

### 阶段二：边输入槽标准化

文件：

- `backend/harness/runtime/compiler.py`
- `backend/harness/graph/context_materializer.py`

动作：

1. 将 `inbound_edge_contexts` 编译成 `authorized_inputs`。
2. 每个输入槽只保留：
   - `slot`
   - `label`
   - `source_title`
   - `content`
   - `artifact_refs` 的用户可理解路径
3. packet id、edge id、result ref 留在 runtime，不进入模型。

完成标准：

- 下游节点仍能收到上游正文。
- 模型消息中不出现完整 flow packet。
- 测试覆盖“多条边输入不会混槽”。

### 阶段三：记忆快照瘦身

文件：

- `backend/harness/runtime/compiler.py`
- `backend/harness/graph/memory_context.py`

动作：

1. 将 memory contract 编译成 `memory.visible_snapshots`。
2. 每个 snapshot 只保留：
   - `label`
   - `collection`
   - `summary`
   - `canonical_text`
   - `read_only/frozen/candidate` 标志
3. 删除模型可见的 namespace、repository lifecycle、write owner、read rule 全表。

完成标准：

- 模型能看到授权记忆内容。
- runtime 仍能按 namespace 精确读写。
- 模型消息不出现 `graphmem:` namespace。

### 阶段四：输出合同瘦身

文件：

- `backend/harness/runtime/compiler.py`
- `backend/harness/graph/output_policy.py`
- `backend/harness/graph/work_order_executor.py`

动作：

1. 模型只看 `output.model_visible_requirements`。
2. artifact materializer 继续从完整 `graph_slot.output_contract` 读写入策略。
3. 输出路径可见，但 repository/root/subdir/materialization 细节不可见。

完成标准：

- 节点产物仍写入创作环境产物区。
- 模型消息中不出现 repository 写入策略。

### 阶段五：重复 prompt 合并

文件：

- `backend/query/runtime.py`
- `backend/harness/runtime/compiler.py`
- `backend/harness/graph/context_materializer.py`

动作：

1. runtime contract 中只保留一个模型可见 `node_prompt`。
2. `user_visible_goal`、`task_run_goal` 不再重复携带完整 role prompt。
3. `input_package.agent_instruction` 只作为 runtime fallback，不进入模型消息。

完成标准：

- 同一角色 prompt 在模型消息中只出现一次。
- graph 节点仍能获得正确角色身份和任务边界。

## 7. 测试计划

需要新增或修改测试：

- `backend/tests/graph_node_prompt_budget_regression.py`
- `backend/tests/graph_task_runtime_facade_regression.py`
- `backend/tests/graph_flow_edge_projection_regression.py`
- `backend/tests/formal_memory_run_scope_regression.py`

关键断言：

1. `input_package` 不出现在模型消息中。
2. `graph_slot` 完整结构不出现在模型消息中。
3. 模型消息包含 `graph_node_context` 或等价瘦身结构。
4. `authorized_inputs` 包含上游授权内容。
5. 多输入槽不会串槽。
6. 记忆 namespace 不进入模型消息，但 memory receipts 仍按 graph run 隔离。
7. artifact 写入仍落到 `storage/task_environments/creation/writing/artifacts/{project}`。
8. 角色设计节点 stable contract 小于 20KB。
9. 审核/路由/记忆节点 stable contract 小于 16KB。
10. 正文写手节点可以看到章节所需记忆，但不能看到未授权上下文。

## 8. 禁止的修法

不得采用以下修法：

- 只把 prompt 文案写短，但继续传完整 `graph_slot`。
- 只增加 token budget 或超时时间。
- 用字符串替换删除局部字段，而不建立模型可见投影结构。
- 把 runtime-only 字段改名后继续送进模型。
- 为写作图写专用绕路逻辑，绕开通用 GraphHarness 编译器。
- 删除边契约或记忆契约本身。
- 把工具调用重新绑定到节点外部隐藏逻辑。

## 9. 验收标准

本优化完成后，图任务系统必须满足：

1. 图编辑器产出的节点契约、边契约、记忆协议、拓扑状态仍直接对接 GraphRuntime / GraphLoop。
2. 完整合同仍由 runtime 持久化和执行。
3. 模型只看到执行当前节点所需的最小语义合同。
4. 边契约继续决定下游上下文新增哪些上游内容。
5. 记忆协议继续决定可读写哪些记忆内容。
6. prompt 不再包含 checkpoint、work order、config hash、repository lifecycle 等系统内部字段。
7. 写作图能继续从启动包推进到设计、记忆提交、章节正文。
8. 断点恢复和 config lock 不受影响。

## 10. 最终目标

目标不是“少传一点内容”，而是形成稳定的合同分层：

```text
完整合同：给 runtime 执行、恢复、校验、写入。
语义合同：给模型理解角色、输入、输出和禁止事项。
边协议：由 runtime 执行成授权输入槽。
记忆协议：由 runtime 执行成授权记忆快照。
输出协议：由 runtime 执行成 artifact 和 memory receipts。
```

只有这样，图编辑器、GraphRuntime、GraphLoop、单节点 agent 和记忆库才能保持同一套协议，同时避免把系统内部结构塞进模型 prompt。
