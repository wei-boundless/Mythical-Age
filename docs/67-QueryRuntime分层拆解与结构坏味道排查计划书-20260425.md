# 67-QueryRuntime分层拆解与结构坏味道排查计划书-20260425

## 一、结论

`backend/query/runtime.py` 当前不是“有很多无用链路”，而是“活链路过多且职责堆叠到同一入口文件”。  
文件现状：

- 总行数约 `2944`
- 方法数约 `107`
- 同时承担了：
  - 查询执行编排
  - follow-up / binding 续接
  - session memory projection
  - direct tool execution
  - PDF / RAG / memory 输出后处理
  - assistant message 持久化与收口

这已经构成典型的 runtime God Object。  
因此本计划书的目标不是“删掉没用代码”，而是：

1. 保留当前有效执行链
2. 先做无行为变化的职责分层
3. 再收缩跨层耦合
4. 最后把 `QueryRuntime` 降回编排器，而不是全能对象

---

## 二、对齐设计原则

本计划与 `docs/设计原则` 中的以下方向保持一致：

- **默认隔离、显式共享**
  参考 `12-Agent-系统.md`、`25-架构模式总结.md`
  状态传递必须显式，不允许 runtime 内部隐式横穿多个职责层。

- **状态源与业务逻辑分离**
  参考 `03-状态管理.md`
  状态加载、投影、恢复不应与执行链、输出链混在同一个对象里。

- **安全边界 fail-closed**
  参考 `09-工具系统设计.md`、`10-BashTool-深度剖析.md`
  contract、permission、fallback 等守卫链路保留，但应下沉到独立 bridge / policy 层。

- **缓存 / prompt /输出按边界切块**
  参考 `07-Prompt-Cache.md`
  输出后处理与执行编排要按“边界”拆分，避免任何小修改都触碰主执行链。

- **大文件不是原罪，但必须有强内聚**
  参考 `01-项目全景.md`
  当前 `runtime.py` 虽大，但其内部不是单一职责的大文件，而是多系统并置，因此已超过合理边界。

---

## 三、现状排查

### 3.1 当前职责分布

按代码段粗分，`backend/query/runtime.py` 当前包含：

- `226-879`：主查询执行链
  - `astream`
  - `_execution_events`
  - `_stream_bundle_execution`
  - `_stream_single_execution`
  - `_stream_planned_execution`

- `880-980`：post-turn 任务与 session memory 刷新

- `999-1274`：main context / task summary / constraints 汇总

- `1275-1808`：projection、binding snapshot、authoritative context、follow-up 续接

- `1809-1956`：session summary 特判与总结辅助

- `2012-2462`：direct tool execution 主桥

- `2492-2918`：RAG/PDF/memory 输出后处理与 fallback policy

- `2933-3111`：assistant message sanitize / persistence gate / segment 组装

### 3.2 结构坏味道

以下问题已可以明确判定为结构性问题：

#### 问题 A：单文件承担过多运行时子系统

`QueryRuntime` 既是入口，又是：

- planner adapter
- execution coordinator
- follow-up resolver adapter
- tool bridge
- output finalizer
- persistence gate
- session memory projection bridge

这导致任何一类 bug 修复都容易碰到其它链路。

#### 问题 B：状态编排与输出后处理强耦合

例如：

- `_capture_session_memory_projection`
- `_load_session_authoritative_context`
- `_stream_binding_followup`
- `_maybe_finalize_pdf_output`
- `_build_assistant_messages`

这些逻辑属于完全不同层级，但都放在同一对象内共享内部细节，增加了隐式耦合。

#### 问题 C：direct tool 执行桥过厚

`2012-2462` 这一段已经不是“调用工具”，而是一个完整子系统，包含：

- permission
- contract
- tool invoke
- task enrich
- PDF special-case
- final visible answer

这意味着任何工具类问题都必须进 `runtime.py` 修，违反职责边界。

#### 问题 D：输出后处理成为第二条主链

`2492-2918` 这一段实际上形成了独立主链：

- RAG finalize
- PDF finalize
- memory output gate
- fallback policy
- procedural-answer detection

这部分应是 policy 层，而不是 runtime 主体的一部分。

#### 问题 E：重复模式明显，但没有抽象收口

例如：

- `build_system_prompt_for_session`
- `abuild_system_prompt_for_session`
- `_abuild_system_prompt_for_execution`

以及：

- RAG / PDF / memory 各自一套 fallback / finalize / gate

这些重复不一定立刻删除，但必须迁出主入口文件，否则会持续放大维护成本。

#### 问题 F：尾部 persistence 逻辑位置错误

以下方法本质更像 persistence adapter：

- `_finalize_segments`
- `_build_assistant_messages`
- `_assistant_metadata_from_done_event`
- `_apply_assistant_persistence_gate`

它们继续放在 runtime 中，会让“可见输出收口”和“执行编排”互相污染。

---

## 四、判断：哪些是核心链路，哪些只是放错了位置

### 核心且应保留在 Runtime 的

- `astream`
- `_execution_events`
- `_stream_bundle_execution`
- `_stream_single_execution`
- `_stream_planned_execution`
- `_planner_build_plan`

这些属于真正的 runtime 编排器职责。

### 活链路但应迁出的

- follow-up / binding 恢复
- session memory projection
- direct tool execution bridge
- output finalization / fallback
- assistant persistence gate

### 当前未发现的大量死代码

本轮排查未发现成片“明显无人调用的废链路”。  
问题主要不是死代码，而是**活代码堆错层**。

---

## 五、按不同目标的拆分路线

### 路线 A：稳定优先

适用：

- 仍在高频跑长场景
- 不希望近期引入新的执行回归

策略：

1. 先拆输出后处理
2. 再拆 persistence
3. 暂不动 follow-up / tool bridge

优点：

- 风险最小
- 不改主执行链
- 可以先明显缩短文件长度

缺点：

- 状态问题不会立刻改善

### 路线 B：状态边界优先

适用：

- 当前主要痛点是 `active_pdf`、follow-up、bundle subset、软污染

策略：

1. 先拆 follow-up / binding 恢复
2. 再拆 projection / authoritative context
3. 最后才动输出层

优点：

- 直接打到最近高频 bug 根因

缺点：

- 比路线 A 更容易影响长场景稳定性

### 路线 C：工具桥优先

适用：

- 后续准备扩更多 tool
- contract / permission / tool invoke 已经成为主要复杂源

策略：

1. 抽 `runtime_tools.py`
2. 再抽 `runtime_pdf_bridge.py`

优点：

- 工具链最清晰

缺点：

- 会直接触碰主执行链

### 推荐路线：A + B 的保守组合

当前最推荐：

1. 先拆输出后处理
2. 再拆 persistence
3. 然后拆 follow-up / binding
4. 工具桥最后处理

原因：

- 先做最独立的搬迁
- 再处理最痛的状态问题
- 最后动最重的 direct tool bridge

---

## 六、实施批次

### Phase 1：输出后处理迁出

新增文件建议：

- `backend/query/runtime_output_policy.py`

迁出方法：

- `_maybe_finalize_rag_output`
- `_rewrite_rag_answer_with_model`
- `_rag_evidence_pack_can_finalize`
- `_fallback_rag_output_response`
- `_maybe_gate_memory_output`
- `_memory_output_needs_gate`
- `_fallback_memory_output_response`
- `_maybe_finalize_pdf_output`
- `_extract_pdf_canonical_from_output_response`
- `_pdf_canonical_can_finalize`
- `_fallback_pdf_output_response`
- `_looks_like_rag_procedural_answer`
- `_looks_like_pdf_procedural_answer`
- `_build_pdf_answer_finalization_messages`
- `_pdf_tool_result_can_use_model_finalization`
- `_pdf_canonical_has_finalizable_evidence`
- `_pdf_tool_decision_is_persistable`
- `_merge_summary_key_points`
- `_pdf_task_kind_from_mode`
- `_normalize_pdf_scope`

目标：

- `runtime.py` 减去最大的一块 policy 堆积
- 0 行为变化

验收：

- 现有 PDF / RAG / memory 回归全通过
- 长场景不新增输出类回退

### Phase 2：assistant persistence 迁出

新增文件建议：

- `backend/query/runtime_persistence.py`

迁出方法：

- `_is_internal_skill_read_tool_call`
- `_looks_like_skill_document`
- `_sanitize_tool_call`
- `_finalize_segments`
- `_build_assistant_messages`
- `_assistant_metadata_from_done_event`
- `_apply_assistant_persistence_gate`
- `_has_completed_tool_receipt`

目标：

- 把“执行”和“落库前清洗”断开

验收：

- assistant 持久化格式不变
- tool_calls sanitize 行为不变

### Phase 3：follow-up / binding 恢复迁出

新增文件建议：

- `backend/query/runtime_followup.py`
- `backend/query/runtime_context_state.py`

迁出方法：

- `_capture_session_memory_projection`
- `_load_session_binding_snapshot`
- `_load_session_authoritative_context`
- `_apply_execution_binding_to_constraints`
- `_binding_identity_from_constraints`
- `_extract_active_constraints`
- `_should_answer_from_followup`
- `_followup_results_from_resolution`
- `_followup_results_from_task_ids`
- `_followup_result_from_done_event`
- `_synthesize_followup_task_summary_ref`
- `_binding_owner_task`
- `_should_execute_binding_followup`
- `_normalize_binding_identity`
- `_binding_execution_from_owner`
- `_stream_binding_followup`
- `_resolved_*`

目标：

- 把状态恢复与执行编排解耦
- 减少 authority / binding 类 bug 的排查成本

验收：

- binding follow-up 回归通过
- active_pdf / active_dataset 恢复回归通过

### Phase 4：direct tool bridge 迁出

新增文件建议：

- `backend/query/runtime_tools.py`

迁出方法：

- `_allowed_tool_names_for_plan`
- `_allowed_tool_names_for_execution`
- `_stream_direct_tool_execution`
- `_evaluate_tool_contract`
- `_effective_tool_contract_mode`
- `_tool_contract_failure_message`
- `_normalize_direct_tool_output`
- `_build_direct_tool_output_decision`
- `_prepare_direct_tool_output_candidate`
- `_stringify_tool_output`
- `_enrich_direct_tool_task`
- `_apply_pdf_persistence_gate`
- `_finalize_pdf_direct_tool_answer`
- `_rewrite_pdf_answer_with_model`

目标：

- runtime 主体只保留 orchestration

验收：

- tool contract regression 全通过
- PDF / structured / weather / gold 工具链不退化

---

## 七、建议目标形态

最终建议结构：

- `runtime.py`
  - 只保留入口与执行编排

- `runtime_output_policy.py`
  - 输出 finalize / fallback / gate

- `runtime_persistence.py`
  - segment 组装 / assistant message 持久化

- `runtime_followup.py`
  - follow-up 解析与绑定恢复

- `runtime_context_state.py`
  - session projection / authoritative context / main context build

- `runtime_tools.py`
  - direct tool 执行桥

---

## 八、禁止事项

为避免再次引入结构回退，本次重构期间禁止：

- 一边拆文件一边改业务行为
- 同一批提交同时重构 runtime 与 planner 主逻辑
- 为了“减少行数”而新增更多隐式 helper，导致跨文件耦合更强
- 在没有回归的情况下直接合并 follow-up / tool bridge 改动

---

## 九、当前判定的“问题结构”

本轮排查后，可明确记录如下：

### 必须处理

- `QueryRuntime` 已经是 God Object
- 执行、状态、输出、持久化四层混杂
- follow-up / authoritative context 相关逻辑过于集中
- 输出后处理成为隐藏第二主链

### 应尽快处理

- prompt build 入口重复
- RAG/PDF/memory fallback pattern 重复
- assistant persistence gate 与 runtime 主链耦合

### 暂不判定为问题

- 文件大本身
- 工具特判本身
- post-turn memory refresh 本身

问题不在“存在这些逻辑”，而在“这些逻辑没有分层”。

---

## 十、推荐执行顺序

建议按以下顺序推进：

1. Phase 1：输出后处理迁出
2. Phase 2：assistant persistence 迁出
3. Phase 3：follow-up / binding 恢复迁出
4. Phase 4：direct tool bridge 迁出

这是当前风险最小、收益最大的路线。

