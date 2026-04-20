# Claude 式长期记忆逐文件实施清单

> 目的：把 [29-长期记忆重构方案.md](/D:/AI应用/langchain-agent/docs/29-长期记忆重构方案.md) 的蓝图，和 [30-长期记忆重构收口清单.md](/D:/AI应用/langchain-agent/docs/30-长期记忆重构收口清单.md) 的问题收口，进一步展开成一份可直接执行的逐文件实施清单。
>
> 这份清单严格以 Claude Code 已验证的 memory 机制为参照：
>
> - 独立 side-query 的 relevant memory recall
> - 独立 forked extraction agent 的 durable write review
> - memory manifest/header 先筛选，topic note 后展开
> - taxonomy + what-not-to-save 约束
> - 游标、互斥、trailing run、主线程与子线程双写互斥

---

## 0. 收尾状态（2026-04-21）

这份清单在本轮重构结束时，不再作为“待开工蓝图”使用，而是作为“已实施清单 + 残留观察项”归档。

### 0.1 本轮已落地的核心项

- 已落地 manifest/header 扫描与轻量索引读取：
  - `backend/memory/manifest_scan.py`
- 已落地 durable recall 协议与独立 recall 子链路：
  - `backend/memory/read_models.py`
  - `backend/memory/read_agent.py`
  - `backend/memory/durable.py`
  - `backend/memory/facade.py`
- 已落地 durable write 协议与 policy/planner/writer 分层骨架：
  - `backend/memory/write_models.py`
  - `backend/memory/write_agent.py`
  - `backend/memory/admission_policy.py`
  - `backend/memory/mutation_planner.py`
  - `backend/memory/store_writer.py`
- 已完成 `memory_intent.py` 降级：
  - 不再让 semantic marker 直接决定 durable recall 主路径
- 已切断 session memory -> durable candidate 主回流：
  - `backend/structured_memory/session_memory.py`
  - `backend/structured_memory/process_state.py`
  - `backend/structured_memory/process_engine.py`
- 已移除旧主路径文件：
  - `backend/structured_memory/durable_candidates.py` 已退出生产链路
- 已将 recall async 边界修正为可在异步主链安全运行：
  - 避免在事件循环中调用 `asyncio.run()`

### 0.2 本轮已完成的验证

- 定向回归已通过：
  - durable recall / facade / runtime route guard
- 更大范围 memory 回归已通过：
  - 先前已跑过的相关 regression 共 71 项通过
- 2026-04-21 长场景验证结果：
  - `compound-task-decomposition-and-focus-return` 通过
  - `memory-preference-and-cross-session-recall` 通过
  - `multi-session-workbench-isolation` 通过
  - `sixty-turn-real-user-marathon` 存在偶发语义漂移，但无确定性代码崩溃

### 0.3 本轮接受的非阻塞残留

- `sixty-turn-real-user-marathon` 在完整四场景重跑时仍有少量偶发漂移：
  - 一次表现为 memory 问答回答成“准备去读 durable file”
  - 一次表现为“先给结论”偏好被回答成更泛化的处理步骤
- 该问题目前归类为 `known flakiness`，不再阻塞本轮收口，原因是：
  - 同类场景单独重跑可通过
  - 已确认不存在确定性崩溃
  - 主链路边界问题已明显收敛

### 0.4 本清单的收尾结论

- 本轮目标按“工程收口”标准视为完成
- 后续若继续优化，不再以“补齐本清单”为目标，而应单独开新清单处理：
  - memory route 的直接回答稳定性
  - 长上下文下的 follow-up 语义漂移
  - 长跑场景的 flaky 断言治理

---

## 1. 目标结论

本轮长期记忆重构，不再继续修补：

- `memory_intent.py` 里的语义触发词读路由
- `durable_candidates.py` 里的 marker 驱动候选生成
- “把 prompt 再写好一点”式的补丁

本轮的正式目标是把长期记忆系统改成 3 层分工：

1. 主线程只做编排，不做长期记忆语义判别
2. memory read 由独立 `MemoryReadAgent` 决定是否召回、召回哪几条
3. durable write 由独立 `DurableWriteExtractorAgent` 生成候选，再由 deterministic policy 决定是否落盘

也就是说：

- LLM 负责语义选择
- 代码负责边界纪律

---

## 2. Claude Code 里要复刻的关键细节

这部分不是理念，而是必须落到代码里的机制。

### 2.1 Recall 机制

Claude Code 的 recall 不是：

- 把所有 memory 注入 prompt
- 或靠主线程 marker 判断要不要查 memory

而是：

1. 扫描 memory 目录，读取每个 note 的 header/frontmatter
2. 生成 manifest
3. 用 side query 选择少量相关 memory 文件
4. 只展开被选中的文件

本项目必须复刻的点：

- header-scan 先于正文读取
- selected notes 数量必须严格有上限
- recall 决策必须发生在独立请求上下文
- 主线程只拿结构化 recall 结果和少量 summaries

### 2.2 Extraction 机制

Claude Code 的 extraction 不是：

- 主线程一句话里出现“记住”“偏好”就立刻写 durable

而是：

1. 每轮结束后异步触发 extraction
2. 只看自上次游标以后新增的 model-visible messages
3. 如果主线程本轮已经写过 memory，则跳过 extraction
4. extraction 在独立 forked agent 中运行
5. extraction 失败不影响主线程答复
6. 如果 extraction 运行时又来了新 turn，则只保留最新 context 作为 trailing run

本项目必须复刻的点：

- `last_processed_message_id` 游标
- `in_progress` 互斥
- `pending_context` trailing run
- 主线程 direct write 与 background extract 双写互斥
- extraction best-effort，不阻塞主响应

### 2.3 Taxonomy 与边界纪律

Claude Code 不是“任何用户显式说记住都写”。

本项目必须建立同等级别的 durable taxonomy：

- `user`
- `feedback`
- `project`
- `reference`

并明确落库禁止项：

- 当前任务步骤
- 当前工具结果
- 当前检索片段
- 当前工作流绑定
- 当前对话临时状态
- 可从代码、repo、git、文件直接推导的信息
- 情绪、称呼、短期语气
- 活动清单、PR 列表、流水账式总结

---

## 3. 本轮不做的事

为了防止范围膨胀，这一轮明确不做以下事情：

- 不迁移到 LangGraph / AutoGen / Letta / MemGPT
- 不引入数据库或向量库作为 durable store 基础设施
- 不把整个 runtime 改写成多 agent framework
- 不让子 agent 直接接管用户主对话
- 不做 durable store 的大规模历史清洗迁移脚本
- 不依赖“补 prompt”作为核心修复手段

---

## 4. 目标模块图

本轮实施完成后，长期记忆主链路应变成下面这组模块：

### 4.1 Read Path

- `MemoryManifestScanner`
- `MemoryReadModels`
- `MemoryReadAgent`
- `MemoryRecallOrchestrator`
- `DurableMemoryRenderer`

### 4.2 Write Path

- `MemoryWriteModels`
- `DurableWriteExtractorAgent`
- `DurableAdmissionPolicy`
- `DurableMutationPlanner`
- `DurableStoreWriter`

### 4.3 Orchestration

- `MemoryFacade`
- `QueryRuntime`
- `SessionMemoryManager`

---

## 5. 阶段拆分

实施顺序不能乱。必须按下面阶段推进。

### Phase 0：接口与观测护栏

目标：

- 在不动主逻辑的前提下先补模型、trace、测试锚点

退出条件：

- 可以观测每次 recall/extraction 的输入、输出、跳过原因、命中结果

### Phase 1：Manifest/Header 层落地

目标：

- durable read 不再默认依赖 full note scan

退出条件：

- durable store 可通过 scanner 输出稳定 `MemoryHeader[]`

### Phase 2：Read Agent 落地

目标：

- durable recall 从 `memory_intent` 主路由中拆出

退出条件：

- recall 由独立 side request 完成

### Phase 3：Write Agent 落地

目标：

- durable candidate 不再由 marker bucket 主导

退出条件：

- extraction 可异步产出 `DurableCandidateDraft[]`

### Phase 4：Admission Policy 与 Mutation Plan

目标：

- LLM 不直接写 durable file

退出条件：

- 所有 durable 变更都必须经过 deterministic policy

### Phase 5：主线程接线与旧路径降级

目标：

- 旧的 heuristic read/write 主路径退出

退出条件：

- `memory_intent.py` 不再决定 durable recall
- `durable_candidates.py` 不再承担 durable candidate 主生成职责

### Phase 6：回归与长场景验证

目标：

- 验证长期记忆不再污染主线程

退出条件：

- targeted regression 和长场景通过

---

## 6. 逐文件实施清单

下面按文件展开，不遗漏新增、修改、降级、兼容和删除职责。

### 6.1 新增 [backend/memory/manifest_scan.py](/D:/AI应用/langchain-agent/backend/memory/manifest_scan.py)

职责：

- 扫描 `durable_memory/notes/**/*.md`
- 只读取 frontmatter 与有限 header 行
- 生成 manifest header 列表

必须新增的类型：

- `MemoryHeader`
- `MemoryManifest`

`MemoryHeader` 字段：

- `note_id`
- `filename`
- `file_path`
- `memory_type`
- `memory_class`
- `title`
- `description`
- `status`
- `confidence`
- `updated_at`
- `retrieval_hints`
- `eligible_for_injection`

必须实现的函数：

- `scan_memory_headers(root_dir: Path, limit: int = 200) -> list[MemoryHeader]`
- `format_memory_manifest(headers: list[MemoryHeader]) -> str`
- `load_memory_header(file_path: Path) -> MemoryHeader | None`

工程要求：

- 按 `updated_at` 或文件 mtime 倒序
- 默认最多 200 条
- 不读取正文全文
- 对坏 frontmatter 容错，返回 `None` 或 degraded header

测试：

- manifest 输出顺序稳定
- frontmatter 缺失时可降级
- 不会把 `MEMORY.md` 当成普通 note

### 6.2 新增 [backend/memory/read_models.py](/D:/AI应用/langchain-agent/backend/memory/read_models.py)

职责：

- 定义 recall side request 的输入输出协议

必须新增的模型：

- `MemoryRecallRequest`
- `MemoryRecallSelection`
- `MemoryRecallResult`
- `RecallReason`

推荐字段：

`MemoryRecallRequest`

- `query`
- `main_context`
- `task_summaries`
- `session_summary`
- `manifest_headers`
- `recently_surfaced_note_ids`
- `explicit_memory_mode`
- `ignore_memory`
- `recent_tools`

`MemoryRecallSelection`

- `should_recall`
- `selected_note_ids`
- `reason`
- `confidence`
- `needs_verification`
- `manifest_only`

`MemoryRecallResult`

- `selection`
- `selected_headers`
- `selected_notes`
- `rendered_summary`

要求：

- `read_models.py` 只放协议，不放业务逻辑
- 输入输出字段必须可序列化，便于 trace 和测试断言

### 6.3 新增 [backend/memory/write_models.py](/D:/AI应用/langchain-agent/backend/memory/write_models.py)

职责：

- 定义 write extraction 与 policy 的协议

必须新增的模型：

- `DurableExtractionBundle`
- `DurableCandidateDraft`
- `DurableAdmissionDecision`
- `DurableMutationPlan`
- `DurableMutationAction`

`DurableExtractionBundle` 建议字段：

- `session_id`
- `turn_id`
- `message_slice`
- `main_context`
- `task_summaries`
- `corrections`
- `session_projection`
- `manifest_headers`

`DurableCandidateDraft` 建议字段：

- `draft_id`
- `memory_type`
- `memory_class`
- `title`
- `canonical_statement`
- `why`
- `how_to_apply`
- `stability`
- `non_obvious_value`
- `source_scope`
- `evidence_excerpt`
- `target_note_id`
- `proposed_action`

`DurableAdmissionDecision` 建议字段：

- `decision`
- `reason`
- `normalized_candidate`
- `matched_note_id`
- `conflicts_with`

`DurableMutationPlan` 建议字段：

- `actions`
- `index_updates`
- `notes_to_create`
- `notes_to_update`
- `notes_to_deprecate`

### 6.4 新增 [backend/memory/read_agent.py](/D:/AI应用/langchain-agent/backend/memory/read_agent.py)

职责：

- 发起独立的 memory recall side request
- 根据 query + manifest headers 选择少量 note ids

必须实现的类：

- `MemoryReadAgent`

必须实现的方法：

- `select_relevant(request: MemoryRecallRequest) -> MemoryRecallSelection`

实现要求：

- 使用单独的 LLM 调用，不共享主线程本轮脏 prompt
- 输入只允许：
  - query
  - main context summary
  - task summaries
  - session summary
  - manifest
  - recent tools
- 严禁直接塞入完整对话历史

输出要求：

- 结构化 JSON
- 只返回 note ids，不返回最终用户话术

Prompt 约束要点：

- 只有“确定有用”才选
- 不确定就返回空
- 用户要求 ignore memory 时必须返回空
- 当前已在使用某工具时，不要选“工具使用参考型” memory，除非是 warning/gotcha

测试：

- 一般 query 返回空
- 显式 memory query 可返回 manifest-only
- 偏好/项目方向 query 返回少量 note ids，不超过上限

### 6.5 新增 [backend/memory/write_agent.py](/D:/AI应用/langchain-agent/backend/memory/write_agent.py)

职责：

- 在独立请求上下文中从 turn bundle 抽取 durable candidate drafts

必须实现的类：

- `DurableWriteExtractorAgent`

必须实现的方法：

- `extract(bundle: DurableExtractionBundle) -> list[DurableCandidateDraft]`

输入要求：

- 只看当前 turn slice 与投影摘要
- 不重新读取整个 session transcript
- 不允许访问 repo 文件或工具输出详情

Prompt 约束要点：

- 只提取跨会话稳定、非显而易见、值得长期保留的信息
- 用户显式要求记住也不能突破 what-not-to-save 边界
- 先判断应更新现有 note 还是创建新 note
- 允许返回空列表

输出要求：

- 一轮默认最多 3 个 draft
- draft 必须归类到 `user / feedback / project / reference`

测试：

- “记住这周做了什么”应返回空或仅抽出 non-obvious 结论
- “以后回答先给结论”应被抽成 `feedback` 或 `user`
- “当前先看 pdf 第 3 页”不能进入 durable

### 6.6 新增 [backend/memory/admission_policy.py](/D:/AI应用/langchain-agent/backend/memory/admission_policy.py)

职责：

- 对 LLM draft 做 deterministic gate

必须实现的类：

- `DurableAdmissionPolicy`

必须实现的方法：

- `evaluate(draft: DurableCandidateDraft, existing_headers: list[MemoryHeader]) -> DurableAdmissionDecision`
- `evaluate_many(...) -> list[DurableAdmissionDecision]`

必须硬编码的规则：

- derivable from repo/file/git/state -> reject
- task-local / tool-local / retrieval-local -> reject
- temporary emotional or conversational state -> reject
- duplicate existing memory -> update/merge
- conflicting existing memory -> supersede/deprecate
- low stability or low non-obvious value -> reject or session_only

要求：

- policy 判断结果必须带 reason code，便于测试
- 不能依赖 prompt 解释作为唯一治理手段

建议 reason code：

- `derivable_state`
- `ephemeral_task_local`
- `tool_output_noise`
- `duplicate_existing`
- `conflicts_existing`
- `stable_and_admissible`
- `insufficient_value`

### 6.7 新增 [backend/memory/mutation_planner.py](/D:/AI应用/langchain-agent/backend/memory/mutation_planner.py)

职责：

- 把 admission decision 转成具体文件变更

必须实现的类：

- `DurableMutationPlanner`

必须实现的方法：

- `build_plan(decisions: list[DurableAdmissionDecision], existing_headers: list[MemoryHeader]) -> DurableMutationPlan`

必须支持的动作：

- `create_note`
- `update_note`
- `supersede_note`
- `deprecate_note`
- `delete_note`
- `update_manifest`

要求：

- `MEMORY.md` 只维护索引行
- topic note 是真相源
- supersede 时要更新旧 note 与新 note 的双向引用字段

### 6.8 新增 [backend/memory/store_writer.py](/D:/AI应用/langchain-agent/backend/memory/store_writer.py)

职责：

- 执行 mutation plan，落盘 durable note 与 manifest

必须实现的类：

- `DurableStoreWriter`

必须实现的方法：

- `apply(plan: DurableMutationPlan) -> dict[str, Any]`

要求：

- 写文件前确保目录存在
- note 文件名稳定、可 slugify
- index 更新幂等
- 失败时不留下半更新状态

测试：

- 重复 apply 同一 plan 不产生重复 index
- update/supersede 后 note 内容和 manifest 一致

### 6.9 修改 [backend/memory/durable.py](/D:/AI应用/langchain-agent/backend/memory/durable.py)

当前问题：

- recall 仍绑定 `memory_intent.memory_read_mode == durable_exact`
- `_infer_relevant_classes()` 仍是 marker fallback
- selected durable context 的组织仍是旧路径兼容产物

改造要求：

- 引入 `manifest_scan.py`
- 引入 `read_agent.py`
- 引入 `admission_policy.py`
- 引入 `mutation_planner.py`
- 引入 `store_writer.py`

新增字段或依赖：

- `self.manifest_scanner`
- `self.read_agent`
- `self.admission_policy`
- `self.mutation_planner`
- `self.store_writer`

必须新增的方法：

- `recall_memories(request: MemoryRecallRequest) -> MemoryRecallResult`
- `submit_extraction_bundle(bundle: DurableExtractionBundle) -> int`
- `extract_and_commit(bundle: DurableExtractionBundle) -> dict[str, Any]`

必须删除或降级的旧职责：

- `_infer_relevant_classes()` 退出主路径
- `_should_prefetch_relevant_notes()` 不再只看 `memory_intent`
- `build_manifest_block()` 只服务显式 inventory query

兼容要求：

- 旧 `prefetch_relevant_notes()` 可暂时保留为 facade compatibility wrapper
- 但内部必须走 `recall_memories()`

### 6.10 修改 [backend/memory/facade.py](/D:/AI应用/langchain-agent/backend/memory/facade.py)

职责调整：

- 从“把旧 session/durable/context 接起来”
- 升级为“统一 memory orchestration 门面”

必须新增接口：

- `recall_durable_memories(...)`
- `submit_durable_extraction_bundle(...)`
- `commit_durable_extraction_bundle(...)`
- `build_memory_recall_request(...)`

必须保留兼容接口：

- `build_persistent_memory_block(...)`
- `prefetch_relevant_notes(...)`

兼容策略：

- 旧接口内部走新 recall orchestrator
- 不允许旧接口继续保留独立 heuristic 路径

### 6.11 修改 [backend/understanding/memory_intent.py](/D:/AI应用/langchain-agent/backend/understanding/memory_intent.py)

当前问题：

- 它还是 durable read/write 主路由器

新的定位：

- 只负责解析“显式 memory 控制信号”
- 不再负责推断 durable recall 语义命中

必须保留的能力：

- `ignore memory`
- `show memory inventory`
- `forget memory`
- `user explicitly asks to remember`

必须降级的能力：

- `SEMANTIC_MEMORY_READ_MARKERS`
- `DURABLE_QUERY_PROFILES`
- 偏好/项目/默认等 marker 推断

最终产物建议：

`MemoryIntent` 只保留以下字段：

- `explicit_read_inventory`
- `explicit_write_request`
- `explicit_forget_request`
- `ignore_memory`
- `should_skip_rag`

要求：

- 它不能再决定 `durable_exact`
- 它只能给 runtime 一个显式信号，真正 recall 由 read agent 决定

### 6.12 修改 [backend/structured_memory/durable_candidates.py](/D:/AI应用/langchain-agent/backend/structured_memory/durable_candidates.py)

当前问题：

- 仍有大量 marker bucket
- 仍承担 durable candidate 主生成职责

新的定位：

- 只保留 legacy normalization / compatibility
- 或逐步退化为测试 fixture helper

必须下线的职责：

- `PREFERENCE_MARKERS`
- `CONVENTION_MARKERS`
- `PROJECT_DECISION_MARKERS`
- `REQUEST_MEMORY_MARKERS`
- `collect_durable_candidates_from_projection(...)` 的主流程职责

允许保留的内容：

- `DurableCandidate` 兼容结构
- `from_dict/to_dict`
- 老测试兼容转换

退出条件：

- runtime 和 session memory 不再依赖这里产主候选

### 6.13 修改 [backend/structured_memory/session_memory.py](/D:/AI应用/langchain-agent/backend/structured_memory/session_memory.py)

当前问题：

- `update_from_context_state()` 已有，但内部还把 projection 继续喂给 durable candidate 路径

必须改动：

- `_build_state_from_context_state(...)` 不再生成 `durable_candidates`
- session state 只负责：
  - active goal
  - task summaries
  - corrections
  - restore hints

本轮要求：

- 至少先切断 session -> durable candidate 直接产出链

下轮可继续：

- 去除 message-centric bridging

### 6.14 修改 [backend/query/runtime.py](/D:/AI应用/langchain-agent/backend/query/runtime.py)

当前问题：

- durable prefetch 仍在主执行路径中过早发生
- recall 与 retrieval、session 恢复、prompt 注入界线仍不够清晰

必须新增步骤：

1. `build_memory_recall_request`
2. `resolve_if_memory_recall_needed`
3. `recall_durable_memories`
4. `submit_durable_extraction_bundle` in post-turn

必须改的函数：

- `_stream_planned_execution(...)`
- `_should_prefetch_durable_context(...)`
- `_run_post_turn_tasks(...)`
- `schedule_durable_memory_extraction(...)`

新顺序要求：

1. build main context
2. session/task-local 恢复
3. retrieval
4. 判断是否需要 durable recall
5. recall selected notes
6. build final prompt

不能再这样做：

- 一进入 turn 就预取 durable
- 把 durable 当常驻背景块

### 6.15 修改 [backend/query/prompt_builder.py](/D:/AI应用/langchain-agent/backend/query/prompt_builder.py)

要求：

- 保持 `static / session / turn` 三段结构
- durable block 只接收 `MemoryRecallResult.rendered_summary`

必须新增约束：

- `turn prompt` 不接收 raw manifest
- `turn prompt` 不接收 raw note body
- `turn prompt` 不接收 recall debug reason

durable 注入格式应改成：

- note title
- canonical statement
- why
- how_to_apply
- freshness hint

不要再注入：

- internal filename
- path
- schema labels
- storage layout

### 6.16 修改 [backend/memory/context.py](/D:/AI应用/langchain-agent/backend/memory/context.py)

当前问题：

- inspect path 和 prompt path 还混着 durable selection 细节

必须改动：

- `inspect_query_context(...)` 展示：
  - recall request summary
  - selected note ids
  - skipped reason
  - extraction scheduled / skipped reason

同时要求：

- inspect 可比 prompt 看到更多调试信息
- 这些调试信息不能反向流回模型

### 6.17 修改 [backend/memory/relevant_selector.py](/D:/AI应用/langchain-agent/backend/memory/relevant_selector.py)

处理方式：

- 不作为主 selector 保留
- 降级为：
  - exact note lookup helper
  - selected note loading helper

原因：

- 真正的选择应交给 `MemoryReadAgent`
- 这里不应继续承担 query semantic selection

### 6.18 修改 [backend/memory/session.py](/D:/AI应用/langchain-agent/backend/memory/session.py)

改动较小：

- 删除对 durable candidate 的隐性依赖
- 保持 session memory 仅作为 working memory layer

### 6.19 新增或修改 [backend/tests/durable_recall_agent_regression.py](/D:/AI应用/langchain-agent/backend/tests/durable_recall_agent_regression.py)

必须覆盖：

- 普通 query 不触发 durable recall
- 显式 inventory query 触发 manifest fallback
- 偏好 query 仅返回少量 selected note ids
- ignore memory 生效
- recent tool 抑噪生效

### 6.20 新增或修改 [backend/tests/durable_write_admission_regression.py](/D:/AI应用/langchain-agent/backend/tests/durable_write_admission_regression.py)

必须覆盖：

- 显式“记住”但内容属 task-local -> reject
- feedback 类型可入 durable
- project 非显而易见背景可入 durable
- reference 只记指针，不记正文
- duplicate -> update
- conflict -> supersede

### 6.21 修改 [backend/tests/session_memory_regression.py](/D:/AI应用/langchain-agent/backend/tests/session_memory_regression.py)

新增断言：

- session memory 不再直接携带 durable candidates
- 当前 task-local 信息不会被 durable extractor 误写

### 6.22 修改 [backend/tests/task_coordinator_regression.py](/D:/AI应用/langchain-agent/backend/tests/task_coordinator_regression.py)

新增断言：

- compound task follow-up 依赖 task/session 恢复，不被 durable 抢路由

### 6.23 新增长场景测试

建议新增：

- `backend/tests/long_memory_recall_boundary_regression.py`

重点场景：

- 长对话中反复切换 pdf / dataset / weather / project preferences
- durable 只在真正需要时召回
- session 恢复优先于 durable recall

---

## 7. 运行时时序清单

这一节专门防止实现时“模块有了，但顺序错了”。

### 7.1 单轮读路径时序

1. 用户消息进入 runtime
2. 构建 `MainContextState`
3. 恢复 session/task-local context
4. 如果需要，执行 retrieval
5. 基于：
   - query
   - main context
   - task summaries
   - session summary
   - explicit memory intent
   - recent tools
   构建 `MemoryRecallRequest`
6. 仅在需要时调用 `MemoryReadAgent`
7. 根据 selection 读取少量 notes
8. 渲染 `durable summary block`
9. 组装最终 prompt
10. 主线程回答

### 7.2 单轮写路径时序

1. turn 完成
2. runtime 收集：
   - 当前新增 message slice
   - main context
   - task summaries
   - corrections
   - session projection
3. 构建 `DurableExtractionBundle`
4. 若本轮已有 direct durable write，则跳过 background extraction
5. 若 extraction 已在运行，则 stash 最新 bundle 为 pending
6. `DurableWriteExtractorAgent` 异步产出 drafts
7. `DurableAdmissionPolicy` 评估 drafts
8. `DurableMutationPlanner` 生成 plan
9. `DurableStoreWriter` 落盘
10. 更新 manifest 与 trace

---

## 8. 游标、互斥、调度细节

这部分必须实现，否则系统稳定性会持续出问题。

### 8.1 必须新增的 extraction runtime state

建议放在 durable layer 内部：

- `last_processed_message_id`
- `in_progress`
- `pending_bundle`
- `turns_since_last_extraction`

### 8.2 游标推进规则

- 只有 extraction 成功完成后才推进游标
- 失败时游标不推进，下次可重试
- 如果游标对应消息已被 compact 清掉，则 fallback 为当前可见消息边界重算

### 8.3 双写互斥

如果未来主线程支持某些显式 durable write 操作，则：

- 同一 turn 主线程已写 durable
- background extractor 必须跳过该 turn

### 8.4 trailing run

如果 extraction 运行时又来了新 turn：

- 不排队多个旧 bundle
- 只保留最新 `pending_bundle`
- 当前 extraction 完成后立刻再跑一轮 trailing extraction

### 8.5 节流

建议增加可配置项：

- 默认每 1-2 个 eligible turn 触发一次 extraction
- trailing run 不受节流限制

---

## 9. Note schema 清单

本轮 durable note schema 至少需要这些字段。

frontmatter 必备：

- `id`
- `type`
- `memory_class`
- `title`
- `description`
- `status`
- `confidence`
- `created_at`
- `updated_at`
- `eligible_for_injection`
- `retrieval_hints`
- `supersedes`
- `superseded_by`
- `review_after`

正文建议固定段落：

- `Canonical:`
- `Why:`
- `How to apply:`
- `Evidence:`

manifest 每行只允许：

- title
- link
- one-line hook
- type/status 短标签

---

## 10. 兼容与下线策略

本轮不是一次性删空所有旧文件，而是严格区分：

### 10.1 保留兼容壳

可以保留：

- `prefetch_relevant_notes(...)`
- `build_persistent_memory_block(...)`
- `DurableCandidate.from_dict()/to_dict()`

但要求：

- 内部必须走新链路
- 不能保留旧 heuristic 旁路

### 10.2 必须退出主路径的旧逻辑

必须退出主路径：

- `memory_intent.py` 的 semantic marker read routing
- `durable_candidates.py` 的 marker-based candidate generation
- `durable.py` 里的 `_infer_relevant_classes()` fallback
- runtime 每轮无条件 durable prefetch
- generic turn 的 manifest fallback

---

## 11. 回归测试清单

本轮实施时，必须同步维护下列断言。

### 11.1 结构断言

- 主 prompt 不含 raw note body
- 主 prompt 不含 durable file path
- recall result 最多展开 N 条 note
- session state 不再产出 durable candidates

### 11.2 语义断言

- “你都记了什么”能走 inventory recall
- “默认回答方式是什么”可召回相关 feedback/user memory
- “继续看第 3 页 pdf”不会错误命中 durable
- “记住这周做了哪些测试”不会进入 durable

### 11.3 稳定性断言

- extraction 失败不影响主线程
- in-progress 时新 turn 只保留最新 pending bundle
- 同一 plan 重复 apply 幂等

### 11.4 长场景断言

- session 恢复优先
- durable 只补充稳定背景
- follow-up 不因 durable recall 漂移

---

## 12. 每阶段退出条件

### Phase 0 退出条件

- trace 中可见 recall/extraction 状态
- 测试框架可断言新的模型协议

### Phase 1 退出条件

- manifest scanner 可稳定输出 headers
- 旧 full scan 不再是 recall 主入口

### Phase 2 退出条件

- recall 由 `MemoryReadAgent` 决定
- `memory_intent.py` 不再决定 durable semantic recall

### Phase 3 退出条件

- write drafts 由 `DurableWriteExtractorAgent` 生成
- `durable_candidates.py` 不再是主候选入口

### Phase 4 退出条件

- 所有 durable 写入都有 admission decision 和 mutation plan
- 无直接“LLM 说写就写”

### Phase 5 退出条件

- runtime 不再每轮 durable prefetch
- manifest fallback 仅用于显式 inventory query

### Phase 6 退出条件

- targeted regression 通过
- 长场景 memory boundary 验证通过

### 阶段收尾状态

- Phase 0：已完成
- Phase 1：已完成
- Phase 2：已完成
- Phase 3：已完成
- Phase 4：已完成
- Phase 5：已完成
- Phase 6：按本轮标准收尾
  - targeted regression 已通过
  - 长场景主链已验证
  - marathon 残余偶发漂移已登记为非阻塞观察项

---

## 13. 推荐实施顺序

真正动手时，建议按下面顺序提交，不要交叉污染：

1. `manifest_scan.py` + `read_models.py` + `write_models.py`
2. `read_agent.py` + `durable.py` recall 路径改造
3. `write_agent.py` + `admission_policy.py` + `mutation_planner.py` + `store_writer.py`
4. `facade.py` + `runtime.py` 接线
5. `memory_intent.py` 降级
6. `durable_candidates.py` 主职责下线
7. `session_memory.py` 断开 durable candidate 回流
8. 测试和长场景验证

---

## 14. 最终验收标准

只有同时满足下面条件，这轮长期记忆重构才算真正完成：

1. durable recall 不再由主线程 marker heuristic 决定
2. durable write 不再由 marker candidate heuristic 决定
3. session memory 与 durable memory 边界被切开
4. `MEMORY.md` 只做轻索引
5. topic notes 只按需展开
6. extraction 具备游标、互斥、trailing run、失败不阻塞
7. 所有 durable 变更都经过 deterministic admission policy
8. 长场景下 durable 不再成为 prompt 污染源

结论：

这份清单的核心，不是“再造一个 memory 功能”，而是把你当前系统里最危险的两个旧主路径彻底下线：

- `memory_intent.py` 的 heuristic read router
- `durable_candidates.py` 的 heuristic write candidate generator

只要这两块还在主路径上，长期记忆系统就仍然是“新壳旧核”。
