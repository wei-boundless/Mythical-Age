# StateMemory 按需召回与 Follow-up 候选化修正计划

## 1. 问题定义

当前失败不是单个 follow-up 判断错误，而是记忆层职责越界：

- `MemoryRuntimeView` 默认读取 `state_snapshot`、`state_candidates`、`restore_candidates`，导致每个 turn 都携带状态记忆。
- `AgentRuntimeChainAssembler` 将 `state_snapshot.context_slots` 转成 `active_bindings` 输入理解层，相当于让状态记忆替当前 turn 决定执行对象。
- follow-up 显式绑定、`resolved_bindings`、`followup_execution_contract` 仍有旧路径残留，容易把上一轮 PDF/数据集误绑定到新请求。
- 这和设计原则冲突：Session/State Memory 应按需读取，compact 时提供摘要；Relevant Memory 是按需召回，不是把所有记忆塞进上下文。

正确目标：

- 当前 turn 的执行事实只能来自显式用户输入、当前任务选择、当前 recipe/skill 决策。
- State Memory 只能作为候选召回证据，帮助 agent 重新定位“刚才那个/这份/继续”等指代。
- 默认构建 runtime 时不读取 state snapshot，也不向理解层注入 active binding。
- 只有意图层判断存在 deictic/follow-up/recovery/resume 需要时，才请求 state 层，并且只产生 `context_recall_candidates`。
- 旧链路必须删除而不是旁路保留：`ContinuationDecision.active_bindings`、由 continuation 生成 `resolved_bindings`、`followup_execution_contract` 注入 TaskSpec、运行时继续合并旧 follow-up contract 都不再允许存在。

## 2. 本地设计依据

- `docs/设计原则/23-Memory系统.md`：Session Memory 不是每轮更新；Relevant Memories 是按需召回，不是全量注入。
- `docs/设计原则/06-上下文管理.md`：compact 后只重建必要上下文，恢复摘要、最近文件、plan、skills，而不是长期暴露状态槽。
- `docs/系统规划/182-主Agent无图长任务与任务图统一运行底座方案-20260520.md`：禁止 `state memory / durable memory active binding` 决定当前 turn 执行对象。

本次落地把这些原则转为硬约束：

- `restore != decide`：恢复候选不能成为执行决定。
- `candidate != binding`：召回候选不能自动进入 `resolved_bindings`。
- `intent gates memory`：先做轻量意图判断，再决定是否请求 state。
- `explicit wins`：显式用户输入和当前 task selection 优先于任何记忆候选。

## 3. 目标执行流

1. 初始内存视图只允许轻量层：默认不读取 `state`，不读取 `conversation`，不读取 `long_term`，除非 profile 明确请求。
2. 意图收集基于当前消息、显式输入、轻量候选诊断，判断是否存在 follow-up/deictic/recovery。
3. 如果需要对象级续接，再构建第二个 memory request：`requested_memory_layers=["state"]`，`state_read_mode="recall_candidates"`。
4. 第二个 memory view 只作为候选证据进入 `continuation_candidates` 和 `context_recall_candidates`。
5. `analyze_query_understanding()` 不再接收从 state slots 派生的 active bindings。
6. `ContextResolver` 只把显式路径写入 `resolved_bindings`；state/restore/task summary 保留为 recall candidates。
7. `TaskSpec.inputs` 不再携带 follow-up 执行契约；子 agent 通信协议只携带候选化的召回证据，且要求子 agent 自行核验候选。
8. 运行时工具请求和委派请求不再读取旧 `followup_execution_contract`；历史 artifact 中若出现该字段也不得再被消费。

## 4. 文件级实施清单

- `backend/memory_system/runtime_view.py`
  - 默认不读取 state snapshot、state candidates、restore candidates。
  - 增加 state 读取模式诊断：`state_read_requested`、`state_read_mode`。
  - 仅 `requested_memory_layers` 明确包含 `state` 时读取 state。

- `backend/memory_system/supply.py`
  - Scope policy 默认不再允许 `conversation/state`，改为请求即授权。
  - 保留 graph/task profile 通过 profile 显式请求 working/task_durable/state 的能力。

- `backend/orchestration/agent_runtime_chain.py`
  - 初始 memory request 使用空层。
  - 删除 state snapshot 到 active bindings 的执行路径。
  - 增加 intent-aware state recall：只有初步 intent 需要 continuation 时才二次读取 state。
  - suppress conversation memory 时不再回退成 state 默认层。

- `backend/intent/signal_collector.py`
  - 增加 `task_summary_candidate_count` 证据。
  - task summary refs 只作为 continuation source availability，不自动绑定。

- `backend/intent/hypothesis_builder.py`
  - `_has_source_candidate` 纳入 `task_summary_candidate_count`。

- `backend/context_management/resolver.py`
  - 删除未使用的 continuation 显式输入/绑定旧函数。
  - `context_recall_candidates` 汇总 continuation、restore、task summary refs。
  - 不让 task summary refs 进入 `resolved_bindings`。

- `backend/continuation/models.py` / `backend/continuation/decision.py` / `backend/continuation/candidate_collector.py`
  - 删除 `ContinuationDecision.active_bindings`。
  - 将候选中的 `binding_payload` 改名为 `recall_payload`，语义上只表示“可供重新定位的证据”。
  - decision 只选择候选、输出目标类型和候选 refs，不输出可执行绑定。

- `backend/tasks/assembly_support.py`
  - follow-up execution contract 降级为候选上下文，不再默认进入 task inputs。
  - 子 agent 通信协议带“候选证据/需要自行核验”的自然语言 handoff，而不是命令式绑定。

- `backend/tests/*`
  - 更新旧 follow-up 测试为候选化断言。
  - 新增默认 memory view 不读取 state 的回归测试。
  - 覆盖 state 明确请求、weather/新任务不被旧 state 污染、task summary refs 候选召回。

## 5. 验证标准

- 默认 `build_memory_runtime_view()` 不含 `state_snapshot` 和 `restore_candidates`。
- 明确 `requested_memory_layers=["state"]` 时才含 state 候选。
- `query_understanding` 不再因为旧 state slots 得到 `active_dataset/active_pdf`。
- follow-up 能看到 `context_recall_candidates`，但 `resolved_bindings` 不自动出现 `continuation_decision`。
- 代码搜索中不存在生产代码读取 `continuation_decision.active_bindings` 或 `followup_execution_contract` 的路径。
- 实时网络/天气/新目标请求不会被旧 PDF/数据集污染。
- 目标回归测试真实通过，不允许伪造结果或绕过测试。

## 6. 回退边界

如测试发现图任务或长任务需要 state，可通过 task/recipe/profile 显式设置：

```json
{
  "requested_memory_layers": ["state"],
  "state_read_mode": "recall_candidates"
}
```

禁止用“空 profile 默认读取 state”作为兼容手段。兼容只能通过明确配置表达，确保普通对话和单 agent 主链路不会被状态记忆污染。

## 7. 实施完成记录

本轮已按计划完成结构性修复：

- `MemoryRuntimeView` 默认不再读取 `state`、`restore_candidates`、`long_term`；只有 profile 显式请求对应 layer 时才读取。
- `AgentRuntimeChainAssembler` 改为先轻量意图识别，再按 intent gate 二次请求 `state` 候选；天气、金价、联网、显式新目标不会触发旧 state 召回。
- `ContinuationDecision` 不再输出 `active_bindings`；候选中的可定位信息统一为 `recall_payload`。
- `ContextResolver` 只把显式用户输入和明确序号任务引用写入 `resolved_bindings`；state/task summary/restore 只进入 `context_recall_candidates`。
- `TaskSpec.inputs` 不再注入 `followup_execution_contract`；子 Agent 通信协议改为携带 `recall_context`，并要求子 Agent 核验候选是否匹配当前请求。
- 运行时 MCP 请求和委派请求不再读取旧 `followup_execution_contract`；需要路径时只从显式输入或 `context_recall_candidates` 推导候选路径。
- `task_understanding/query_understanding` 删除 `active_bindings` 参数和 `bound_*` 死代码，避免理解层绕过意图召回层直接吃 state slot。

补充说明：

- 任务图内部仍存在 `binding_payload`、`task_projection_binding_payload` 等命名，它们属于任务图契约/边绑定，不属于本次删除的 follow-up/state-memory 旧链路。
- `projection_from_bound_answer` 的 “bound” 指当前 turn 已解析的 `resolved_bindings` 答案投影，不读取 state memory，也不恢复 `active_bindings`。

验证记录：

- `python -m py_compile backend\understanding\task_understanding.py backend\context_management\resolver.py backend\tasks\assembly_support.py backend\tasks\execution_shape_resolver.py`
- `python -m py_compile backend\intent\signal_collector.py backend\intent\hypothesis_builder.py backend\understanding\task_understanding.py`
- `python -m pytest backend\tests\intent_continuation_layer_regression.py backend\tests\agent_main_assembly_semantic_boundary_regression.py backend\tests\context_recall_runtime_regression.py backend\tests\skill_runtime_integration_regression.py backend\tests\memory_system_contracts_regression.py backend\tests\runtime_assembly_builder_test.py backend\tests\main_agent_natural_delegation_regression.py backend\tests\context_management_current_turn_regression.py backend\tests\file_work_object_writeback_regression.py -q`
- `python backend\tests\task_understanding_regression.py`
- `python backend\tests\skill_runtime_regression.py`
- 生产代码扫描：`rg -n "followup_execution_contract|continuation_decision\.active_bindings|active_bindings=|active_bindings|bound_dataset_path|bound_pdf_path" backend --glob '!backend/tests/**' --glob '!backend/runtime_state/**' -S` 无命中。
