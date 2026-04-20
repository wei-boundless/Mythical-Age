# Claude式记忆召回与主线程去污逐文件执行清单

> 目的：这份清单不是重复 [31-Claude式长期记忆逐文件实施清单.md](/D:/AI应用/langchain-agent/docs/31-Claude式长期记忆逐文件实施清单.md)，而是在其基础上，针对当前长场景中暴露出来的两类残留问题继续收口：
>
> 1. 长期记忆 recall 仍然被主线程 heuristic gate 拦截，Claude 式 side-query 判别没有真正接管入口
> 2. 主线程 session/process state 仍然把治理性 working-memory 文本暴露给模型，导致 durable recall 未命中时答案被上下文污染带偏
>
> 这份清单严格基于当前代码现状撰写，不是闭门造车的理想蓝图。下面的改造建议均以已经存在的模块为落点，而不是引入新框架重写。

---

## 0. 编写前已核对的现状代码

这份清单是对下面这些实际模块逐个核对之后写出来的：

- `backend/query/planner.py`
- `backend/query/runtime.py`
- `backend/query/prompt_builder.py`
- `backend/query/models.py`
- `backend/query/context_models.py`
- `backend/query/followup_resolver.py`
- `backend/query/answer_assembler.py`
- `backend/understanding/memory_intent.py`
- `backend/understanding/task_understanding.py`
- `backend/memory/durable.py`
- `backend/memory/read_agent.py`
- `backend/memory/read_models.py`
- `backend/memory/facade.py`
- `backend/memory/context.py`
- `backend/memory/session.py`
- `backend/context_management/context_controller.py`
- `backend/context_management/context_models.py`
- `backend/structured_memory/session_memory.py`
- `backend/structured_memory/session_memory_view.py`
- `backend/structured_memory/process_engine.py`
- `backend/structured_memory/extractor.py`
- `backend/tasks/coordinator.py`
- `backend/tasks/models.py`
- `backend/tasks/context_models.py`
- `backend/tests/durable_recall_agent_regression.py`
- `backend/tests/query_runtime_route_guard_regression.py`
- `backend/tests/memory_facade_regression.py`

---

## 1. 当前架构的真实问题，不再泛化描述

### 1.1 当前读链路真实形态

当前长期记忆 recall 不是“主线程直接把判别权交给 recall 子 agent”，而是下面这个顺序：

1. `QueryPlanner` 在 [planner.py](/D:/AI应用/langchain-agent/backend/query/planner.py) 中先运行 `analyze_memory_intent()`
2. `QueryRuntime` 在 [runtime.py](/D:/AI应用/langchain-agent/backend/query/runtime.py) 中依据 `memory_intent` 决定 `_should_prefetch_durable_context()`
3. 只有 gate 通过，才会调用 `prefetch_relevant_notes()` 和后续 recall 子链路
4. `MemoryReadAgent` 在 [read_agent.py](/D:/AI应用/langchain-agent/backend/memory/read_agent.py) 中才真正做“是否召回 / 召回哪些 note”的判别

问题就在于：

- recall 子 agent 已存在，但没有接管 recall 入口判别
- 主线程还保留了一层 heuristic gate
- gate 判错时，子 agent 根本没有机会出手

### 1.2 当前主线程污染的真实入口

当前主线程上下文污染，不是 durable memory 子链路造成的，而是 `session/process state -> context package -> system prompt` 这一段仍然过宽：

- [session_memory_view.py](/D:/AI应用/langchain-agent/backend/structured_memory/session_memory_view.py) 把 `Flow State`、`Risk Watch`、`Next Step`、`Current Task State` 直接渲染为工作视图
- [context_controller.py](/D:/AI应用/langchain-agent/backend/context_management/context_controller.py) 把这些 header 组成 `active_process_context`
- [prompt_builder.py](/D:/AI应用/langchain-agent/backend/query/prompt_builder.py) 又把 `active_process_context` 作为 `Session Memory` 注入模型

这与前面文档中的设计目标已经出现偏差：

- session memory 本应偏恢复索引
- Risk / Next Step / clarification 这类治理语句本应偏 debug / orchestration
- 但现在它们仍然是 model-visible 的工作事实

### 1.3 当前 full compact 会放大这个问题

在 [context_controller.py](/D:/AI应用/langchain-agent/backend/context_management/context_controller.py) 中，`full_compact` 会清空 durable sections，但保留 `active_process_context` 和 `hot_truth_window`。

这意味着一旦 recall 没命中：

- durable context 被压掉
- 主线程 session/process state 反而变成最显眼的上下文
- 历史治理文本会替代 durable facts 主导答案

---

## 2. 本轮改造的正式目标

本轮不是再做一轮“补 marker / 补 prompt”的局部补丁，而是要把主链路调整成接近 Claude Code 的形态：

1. `memory_intent` 只保留极少量显式控制职责，不再主导 recall 入口
2. recall 子 agent 真正接管“要不要 recall”以及“recall 哪几条”
3. session memory 区分 `model-visible restore facts` 与 `debug/governance state`
4. context compaction 在 memory query 下优先保 durable summary，而不是优先保治理文本
5. prompt builder 只注入恢复事实，不注入调度说明

最终要达成的链路是：

`query`
-> `independent recall request`
-> `MemoryReadAgent selection`
-> `small durable injection`
-> `main-thread answer`

而不是：

`query`
-> `memory_intent heuristic gate`
-> `durable recall 没触发`
-> `session/process governance text 顶上`

---

## 3. 本轮明确不做的事情

- 不迁移到 LangGraph / AutoGen / Letta / Zep
- 不引入数据库、向量库、图数据库作为本轮前提
- 不重写整个 runtime
- 不把 follow-up、task、memory 三套系统重新推翻建模
- 不把问题归咎于“模型随机性”而跳过结构收口

---

## 4. 现有模块职责映射

这一节先把“当前谁在做什么”写清楚，避免后面清单混乱。

### 4.1 Query 层

- [planner.py](/D:/AI应用/langchain-agent/backend/query/planner.py)
  - 当前职责：构建 `QueryPlan`，先做 `memory_intent`，再做 `query_understanding`
  - 当前问题：记忆判别前置，造成 recall 入口仍被 heuristic gate 支配

- [runtime.py](/D:/AI应用/langchain-agent/backend/query/runtime.py)
  - 当前职责：主线程编排、检索、memory prefetch、prompt 组装、模型调用、post-turn tasks
  - 当前问题：`_should_prefetch_durable_context()` 仍然是 recall 入口门卫

- [prompt_builder.py](/D:/AI应用/langchain-agent/backend/query/prompt_builder.py)
  - 当前职责：拼 static / session / turn prompt
  - 当前问题：session prompt 仍渲染了过宽的 runtime context

### 4.2 Memory 层

- [durable.py](/D:/AI应用/langchain-agent/backend/memory/durable.py)
  - 当前职责：manifest scan、read agent 调用、durable render、write scheduler 对接
  - 当前问题：`_should_attempt_recall()` 仍有第二层 recall gate

- [read_agent.py](/D:/AI应用/langchain-agent/backend/memory/read_agent.py)
  - 当前职责：根据 `MemoryRecallRequest` 做 `should_recall / selected_note_ids`
  - 当前问题：定位基本正确，但目前只在 gate 放行后才有机会工作

- [facade.py](/D:/AI应用/langchain-agent/backend/memory/facade.py)
  - 当前职责：统一 memory 对外接口
  - 当前问题：接口齐全，但 runtime 没真正让 recall path 成为主路径

### 4.3 Session / Context 层

- [session_memory.py](/D:/AI应用/langchain-agent/backend/structured_memory/session_memory.py)
  - 当前职责：维护 per-session working memory view 和 projection summary
  - 当前问题：render 出来的 state 仍混合恢复事实与治理信息

- [session_memory_view.py](/D:/AI应用/langchain-agent/backend/structured_memory/session_memory_view.py)
  - 当前职责：把 `DialogueState` 渲染成 `agent_view.md` 和 `compaction_view.md`
  - 当前问题：`Flow State / Risk Watch / Next Step` 对模型过度可见

- [context_controller.py](/D:/AI应用/langchain-agent/backend/context_management/context_controller.py)
  - 当前职责：从 session state 选层、压缩、构造 `ContextPackage`
  - 当前问题：当前的 layer-aware 还停留在字符串块层面，且保留了错误的 model-visible section

---

## 5. 目标架构：在当前代码上的落地方式

### 5.1 Recall 入口改成 side-query 优先

目标语义：

- `memory_intent` 不再决定 recall 是否发生
- `MemoryReadAgent` 决定 recall 是否发生
- 主线程默认构造 recall request，再由 recall 子 agent 返回：
  - `should_recall`
  - `selected_note_ids`
  - `manifest_only`
  - `reason`
  - `confidence`

### 5.2 Session memory 分成两种视图

需要明确分出两种视图：

1. `model-visible restore view`
   - 只给模型看
   - 只保留恢复事实

2. `debug/governance view`
   - 只给 trace / inspect / 测试看
   - 保留 `Risk Watch / Next Step / clarification_required / low_flow_confidence`

### 5.3 full compact 下的 memory-aware 策略

对于普通 query，可以继续按现有 budget 压缩。

但对于 memory query / memory-adjacent query，应当引入专门策略：

- 可以减少 active-process governance text
- 保留 manifest summary 或 exact durable summary
- 不允许“durable 被清零但治理文本被保留”为默认行为

---

## 6. 逐文件执行清单

下面进入正式逐文件清单。每个文件都按四项写：

- 当前职责
- 现存问题
- 具体修改
- 回归要求

---

### 6.1 [backend/understanding/memory_intent.py](/D:/AI应用/langchain-agent/backend/understanding/memory_intent.py)

当前职责：

- 用 marker / pattern 产出 `MemoryIntent`
- 决定 `memory_read_mode`、`memory_write_mode`、`should_skip_rag`

现存问题：

- 把 recall 入口 gate 放在这里，职责过重
- `SESSION_MARKERS` 优先级过高，容易把 explicit long-term-memory query 误伤成 session continuity
- preference recall 问句覆盖不全

具体修改：

1. 收缩 `MemoryIntent` 的职责边界，只保留：
   - `ignore_memory`
   - `explicit_read_inventory`
   - `explicit_write_request`
   - `explicit_forget_request`
   - `preferred_types`
   - `preferred_memory_classes`

2. 降级这些字段的语义权重：
   - `memory_read_mode`
   - `should_skip_rag`
   它们可以继续保留兼容，但不能再被当成 recall 主判据

3. 手工 inventory 查询优先级前移：
   - `你刚才帮我长期记住了什么`
   - `你都记了什么`
   必须先于 `SESSION_MARKERS`

4. 保留 `ignore_memory` 作为强控制
   - 这是少数应继续由主线程显式尊重的指令

回归要求：

- `你刚才帮我长期记住了什么？` 不得再落成 `session_continuity_query`
- `以后我问复杂问题时，你应该先怎么回答？` 至少要产出 `preferred_types=["user"]` / `preferred_memory_classes=["preference"]`
- `这次不要用记忆` 必须继续短路 recall

---

### 6.2 [backend/understanding/task_understanding.py](/D:/AI应用/langchain-agent/backend/understanding/task_understanding.py)

当前职责：

- 把 query 判成 weather/pdf/tool/rag/memory 等 route

现存问题：

- 目前 `memory_intent.should_skip_rag` 会直接把 route 拉成 `memory`
- 这让 memory route 的判别仍然过度依赖前置 heuristic

具体修改：

1. 把“是否是 memory route”从 `should_skip_rag` 解耦
2. 引入更窄的 route 触发条件：
   - explicit inventory query
   - explicit ignore-memory query
   - explicit memory-management query
3. 普通 memory-adjacent 问题仍允许 route=`rag` 或 `general`，但 recall side-query 仍会发生

回归要求：

- preference recall 问题可以继续走 `rag`，但 recall side-query 要执行
- inventory 问题应稳定走 memory-oriented path

---

### 6.3 [backend/query/planner.py](/D:/AI应用/langchain-agent/backend/query/planner.py)

当前职责：

- 先做 `memory_intent`
- 再做 `query_understanding`
- 产出 `QueryPlan`

现存问题：

- `memory_intent` 和 `query_understanding` 的耦合过强
- plan 中还没有“recall request is standard sidecar”这个语义

具体修改：

1. 保留 `memory_intent` 结果，但仅作为 recall hint，而非 recall gate
2. 在 `QueryExecutionPlan` 中显式加入：
   - `recall_hints`
   - `memory_query_mode`
   - 或等价的轻量字段
3. 不再让 planner 直接决定“这轮是否查 durable”

回归要求：

- plan 构建后，不需要 `memory_intent.should_skip_rag=True` 才能发生 durable prefetch

---

### 6.4 [backend/query/models.py](/D:/AI应用/langchain-agent/backend/query/models.py)

当前职责：

- `QueryExecutionPlan`
- `QueryPlan`
- `QueryContext`

现存问题：

- `QueryContext` 里没有显式“recall selection result / visible session facts / debug session facts”分层

具体修改：

1. 扩展 `QueryContext`：
   - `durable_recall_result`
   - `session_restore_summary`
   - `session_debug_summary`
2. 保持 dataclass，不引入新框架
3. 保证这三个字段在 runtime 里有独立来源和独立消费方

回归要求：

- memory trace 与 model-visible session summary 必须能在测试中被区分

---

### 6.5 [backend/memory/read_models.py](/D:/AI应用/langchain-agent/backend/memory/read_models.py)

当前职责：

- 定义 `MemoryRecallRequest / Selection / Result`

现存问题：

- request 里虽然已有 `main_context`、`session_summary`，但还缺少“调用目的”与“查询类型”这类显式信息
- selection 结果可用，但还不够支持 runtime 做策略分支

具体修改：

1. 给 `MemoryRecallRequest` 增加：
   - `query_kind`
   - `is_memory_question`
   - `surface_budget_hint`

2. 给 `MemoryRecallSelection` 增加可选字段：
   - `suppress_session_context`
   - `prefer_manifest_summary`

3. 保持 Pydantic，便于 agent 输出校验

回归要求：

- recall 子 agent 的返回可以直接驱动 prompt assembly 策略，不需要 runtime 再猜一次

---

### 6.6 [backend/memory/read_agent.py](/D:/AI应用/langchain-agent/backend/memory/read_agent.py)

当前职责：

- 根据 manifest headers 决定 `should_recall / selected_note_ids`

现存问题：

- 逻辑基本合理，但在主线程没放行时没有机会运行
- fallback 仍然过于依赖 query term overlap

具体修改：

1. 不改它的主职责，改其“调用地位”：
   - 它要从“后半段选择器”升级成“recall 入口判决器”

2. 模型 prompt 增加更明确的选择边界：
   - inventory query 时优先 manifest_only
   - preference / project convention query 时更严格偏向少量 high-confidence note
   - 用户要求忽略记忆时直接 `ignore_memory`

3. fallback 规则增加：
   - 对 preference / answer-style / project-focus 做轻规则增强
   - 但只作为 model failover，不再作为主路径

回归要求：

- 当 model invoker 存在时，runtime 应默认走这里
- model invoker 不存在时，fallback 仍能命中已有稳定案例

---

### 6.7 [backend/memory/durable.py](/D:/AI应用/langchain-agent/backend/memory/durable.py)

当前职责：

- recall orchestration
- durable render
- extraction 调度对接

现存问题：

- `_should_attempt_recall()` 仍形成第二层 recall gate
- recall render 与 recall decision 还没有完全分离

具体修改：

1. 把 `_should_attempt_recall()` 改成“极弱保护”：
   - 仅在 `ignore_memory=True`、空 query、非语言输入等极端条件下跳过
   - 不再基于 marker 决定 recall

2. 明确拆成三个内部阶段：
   - `build_recall_request()`
   - `select_recall_result()`
   - `render_recalled_context()`

3. `build_persistent_memory_block()` / `abuild_persistent_memory_block()` 只负责 render，不再附带 recall gate 语义

4. 对 memory question 场景支持：
   - `manifest_only`
   - exact-only
   - exact+relevant

回归要求：

- runtime 调用该层时，不应因为 `memory_intent=general` 而被静默短路
- async recall 与 sync recall 语义一致

---

### 6.8 [backend/memory/facade.py](/D:/AI应用/langchain-agent/backend/memory/facade.py)

当前职责：

- 统一暴露 recall、session refresh、context package、extraction 等接口

现存问题：

- 接口存在，但 runtime 仍然把它当工具箱，而不是标准 memory pipeline

具体修改：

1. 增加一个显式高层入口，例如：
   - `arecall_for_query(...)`
   - 或 `abuild_query_memory_context(...)`

2. 这个入口内部完成：
   - request build
   - read-agent selection
   - selected notes load
   - render block / summary

3. `inspect_query_context()` 保留，但只作为 debug / trace，不作为模型路径依赖

回归要求：

- runtime 只调用一两个高层接口即可完成 memory recall
- inspect 与 model-visible path 分离

---

### 6.9 [backend/query/runtime.py](/D:/AI应用/langchain-agent/backend/query/runtime.py)

当前职责：

- 主线程编排
- history compaction
- retrieval
- durable prefetch
- memory trace
- prompt build

现存问题：

- `_should_prefetch_durable_context()` 仍是 recall 主门卫
- prompt 组装前，尚未区分 model-visible 和 debug-only session summary

具体修改：

1. 删除或极度削弱 `_should_prefetch_durable_context()`
   - 改成“默认 recall，少数情况跳过”
   - `ignore_memory` 是最重要的跳过条件

2. 在 `_stream_planned_execution()` 中重排顺序：
   - build recall request
   - 调用 recall 子链路
   - 再做 `inspect_query_context()` 作为 trace
   - 再组装 prompt

3. 给 memory-adjacent 问题保留 RAG
   - recall 不等于 memory route
   - `rag + recall` 应成为常态

4. 新增 memory-aware compact policy
   - 当 `selection.should_recall` 或 `manifest_only` 为真时，压缩优先级向 durable summary 倾斜

回归要求：

- “我们项目当前重点是什么” 即便 route=`rag` 也要发生 recall
- “以后我问复杂问题时，你应该先怎么回答” 即便不走 memory route 也要 recall
- “不要使用记忆” 必须不触发 recall

---

### 6.10 [backend/query/prompt_builder.py](/D:/AI应用/langchain-agent/backend/query/prompt_builder.py)

当前职责：

- 构造 `static`、`session memoized`、`turn prompt`

现存问题：

- `build_session_memoized_prompt()` 仍把 `active_process_context` 整块放进模型
- `build_turn_prompt()` 虽然支持 durable-only，但 session block 还没做 model/debug 分裂

具体修改：

1. session prompt 改为只吃 `model-visible restore summary`
2. 不再直接渲染：
   - `Risk Watch`
   - `Next Step`
   - `clarification_required`
   - `low_flow_confidence`
3. `Durable Memory` block 保持 turn-volatile 注入
4. 明确 boundary：
   - static
   - session restore
   - turn durable
   - retrieval evidence

回归要求：

- system prompt 不再出现“先向用户澄清当前目标”这类调度语句
- memory trace 里仍能看到这些字段，但模型 prompt 里不能看到

---

### 6.11 [backend/memory/context.py](/D:/AI应用/langchain-agent/backend/memory/context.py)

当前职责：

- 拼 `ContextPackage`
- 提供 inspect 视图

现存问题：

- `build_session_memory_block()` 与 `inspect_query_context()` 仍共用较多 session state 来源

具体修改：

1. 明确拆成：
   - `build_model_visible_context_package()`
   - `build_debug_context_package()`

2. `inspect_query_context()` 使用 debug package
3. `build_session_memory_block()` 使用 model-visible package

回归要求：

- 同一 session 下，inspect 预览比 model-visible block 更丰富

---

### 6.12 [backend/context_management/context_models.py](/D:/AI应用/langchain-agent/backend/context_management/context_models.py)

当前职责：

- 定义 `ContextPackage`

现存问题：

- sections 仍然是宽松字符串桶，没有“model-visible / debug-only”显式字段

具体修改：

1. 在兼容保留 `sections` 的同时，新增 typed fields：
   - `model_visible_sections`
   - `debug_sections`
   - 或等价命名

2. 保持 `to_dict()` 兼容旧测试，但新增更细的字段供新测试断言

回归要求：

- 测试可以显式断言治理字段是否进入 model-visible 区

---

### 6.13 [backend/context_management/context_controller.py](/D:/AI应用/langchain-agent/backend/context_management/context_controller.py)

当前职责：

- 选 section
- 按 pressure 预算裁剪
- 产出 `ContextPackage`

现存问题：

- `active_process_headers` 仍包含 `# Risk Watch`、`# Next Step`
- `full_compact` 时 durable 被清零，治理文本却常保留

具体修改：

1. 将 `active_process_headers` 拆分：
   - model-visible headers
   - debug-only headers

2. model-visible 只保留：
   - `# Active Goal`
   - 精简后的 `# Flow State`
   - 必要 `# Context Slots`
   - 极简 `# Current Task State`

3. debug-only 保留：
   - `# Risk Watch`
   - `# Next Step`
   - 原始 `Flow State` 细节

4. 引入 memory-aware compaction：
   - memory query 下，`exact_durable_context` 或 manifest summary 至少保留一层
   - 先压 governance，再压 durable summary

5. `_recent_truth_window()` 增加去治理噪声规则
   - 避免把“收到，已记住...”与后续调度语言原样暴露

回归要求：

- full compact 下 memory query 不再出现“durable 空、治理文本满”的结构
- normal pressure 下 model-visible sections 不得包含 `Risk Watch`

---

### 6.14 [backend/structured_memory/session_memory_view.py](/D:/AI应用/langchain-agent/backend/structured_memory/session_memory_view.py)

当前职责：

- 把 `DialogueState` 渲染为 markdown 视图

现存问题：

- 当前只有一套渲染逻辑，被同时用于：
   - agent working view
   - compaction restore view
   - inspect preview

具体修改：

1. 明确拆成两套渲染器：
   - `render_model_view(state)`
   - `render_debug_view(state)`

2. `render_model_view()` 里移除或降级：
   - `Risk Watch`
   - `Next Step`
   - `Flow confidence`
   - `clarification_required`

3. `render_debug_view()` 继续保留原有信息，便于 trace 和排障

4. `render_compaction_view()` 改成基于 model view，而不是基于 full debug view 截断

回归要求：

- compaction view 不再自动包含 governance section
- summary.md / debug preview 可以保留更多信息，但 model-visible block 必须更窄

---

### 6.15 [backend/structured_memory/session_memory.py](/D:/AI应用/langchain-agent/backend/structured_memory/session_memory.py)

当前职责：

- 维护 session memory 存储与 context-state projection

现存问题：

- `load()` 仍默认加载 agent view
- 对调用方来说，model view 与 debug view 还不是明确区分的接口

具体修改：

1. 增加显式接口：
   - `load_model_view()`
   - `load_debug_view()`
   - `compact_model_view()`

2. `update_from_context_state()` 保留 summary-first 思路，但输出的主视图改成 restore-oriented model view
3. 调试富视图可额外落盘到 `views/debug_view.md`

回归要求：

- runtime 构 prompt 只能走 model view
- inspect/trace 可以继续读 debug view

---

### 6.16 [backend/structured_memory/process_engine.py](/D:/AI应用/langchain-agent/backend/structured_memory/process_engine.py)

当前职责：

- 从理解快照组装 `DialogueState`

现存问题：

- 这里仍会产生大量治理性状态，后面又被原样渲染给模型

具体修改：

1. 不必大改状态生成逻辑
2. 重点增加“字段语义标签”或辅助方法，标明哪些字段：
   - 适合恢复
   - 只适合治理

3. 为 `clarification_required` / `low_flow_confidence` 等风险标记提供统一访问接口，供 view 层选择是否渲染

回归要求：

- process engine 可继续输出完整 state
- 但 view/controller 层能准确把治理字段挡在模型之外

---

### 6.17 [backend/memory/session.py](/D:/AI应用/langchain-agent/backend/memory/session.py)

当前职责：

- session memory layer 封装

现存问题：

- `context_controller()` 返回的是当前默认 controller，没有传入 model/debug 视图语义

具体修改：

1. 支持按用途创建 controller：
   - `context_controller(session_id, mode="model")`
   - `context_controller(session_id, mode="debug")`

2. 让 runtime 和 inspect 分别走不同 mode

回归要求：

- facade 层能显式要求构建 model-visible package

---

### 6.18 [backend/memory/relevant_selector.py](/D:/AI应用/langchain-agent/backend/memory/relevant_selector.py)

当前职责：

- 基于 `MemoryManager` 选相关 note

现存问题：

- 这一层在 recall 子链路中的角色已经被 `MemoryReadAgent + manifest scan` 取代了一部分

具体修改：

1. 评估是否继续作为 `selected_headers -> selected_notes` 的加载器保留
2. 如果职责与 `durable.py` 内部实现重复，则收缩或删除其一
3. 避免 recall 逻辑分散在两个模块

回归要求：

- recall path 中“选谁、载谁、渲染谁”三个动作落在单一清晰链路，不再双轨并存

---

### 6.19 [backend/tests/durable_recall_agent_regression.py](/D:/AI应用/langchain-agent/backend/tests/durable_recall_agent_regression.py)

新增/调整测试：

1. 明确新增：
   - inventory query 不因 `刚才` 落成 session continuity
   - preference recall 问题可以在 `general/rag` route 下仍触发 recall

2. 增加 async recall 与 sync recall 一致性断言

3. 增加 `manifest_only` 场景的长期稳定断言

---

### 6.20 [backend/tests/query_runtime_route_guard_regression.py](/D:/AI应用/langchain-agent/backend/tests/query_runtime_route_guard_regression.py)

新增/调整测试：

1. 把现有“semantic memory signal keeps rag and prefetches durable”扩成两类：
   - project focus recall
   - answer style recall

2. 新增 case：
   - `memory_intent.general` 但 recall side-query 仍会触发

3. 断言：
   - runtime 不再只依赖 `_should_prefetch_durable_context()`

---

### 6.21 [backend/tests/memory_facade_regression.py](/D:/AI应用/langchain-agent/backend/tests/memory_facade_regression.py)

新增/调整测试：

1. 增加 `model-visible` 与 `inspect` 分层断言
2. 明确断言：
   - prompt path 中不包含 `Risk Watch`
   - inspect path 中可以包含 `Risk Watch`

---

### 6.22 新增测试文件建议

建议新增：

- `backend/tests/session_prompt_visibility_regression.py`
  - 检查治理字段是否误入 prompt

- `backend/tests/memory_query_compaction_regression.py`
  - 检查 full compact 下 memory query 的 durable 保留策略

- `backend/tests/memory_intent_guard_regression.py`
  - 专门锁定 `刚才 + 长期记忆`、`回答方式 + 偏好` 等案例

---

## 7. 实施顺序

这轮修改不能乱序，建议按下面顺序推进。

### Phase A：先把 recall gate 收掉

涉及文件：

- `backend/understanding/memory_intent.py`
- `backend/understanding/task_understanding.py`
- `backend/query/planner.py`
- `backend/memory/durable.py`
- `backend/query/runtime.py`
- `backend/tests/durable_recall_agent_regression.py`
- `backend/tests/query_runtime_route_guard_regression.py`

退出条件：

- recall 子 agent 真正接管 recall 入口
- turn-22 / turn-26 这类问题不再被前置 gate 静默拦截

### Phase B：再做 session/process 主线程去污

涉及文件：

- `backend/structured_memory/session_memory_view.py`
- `backend/structured_memory/session_memory.py`
- `backend/structured_memory/process_engine.py`
- `backend/context_management/context_models.py`
- `backend/context_management/context_controller.py`
- `backend/memory/context.py`
- `backend/query/prompt_builder.py`
- `backend/tests/memory_facade_regression.py`
- 新增 session prompt visibility / compaction regression

退出条件：

- governance text 不再进入 model-visible prompt
- inspect/debug 仍保留足够排障信息

### Phase C：收口重复路径与死代码

涉及文件：

- `backend/memory/relevant_selector.py`
- `backend/memory/durable.py`
- 可能涉及 `backend/structured_memory/extractor.py` 的兼容逻辑清理

退出条件：

- recall path 没有双轨逻辑
- 不再出现“旧路径在旁边挂着但没人知道还会不会被命中”的维护风险

---

## 8. 验收标准

### 8.1 结构验收

- recall 子 agent 接管 recall 入口判别
- `memory_intent` 不再主导 recall gate
- session memory 有 model/debug 双视图
- context package 有 model-visible/debug 区分
- full compact 对 memory query 具备 memory-aware 策略

### 8.2 行为验收

- `你刚才帮我长期记住了什么？`
  - 优先命中 durable inventory / manifest
  - 不再回答成 session continuity 或工具计划

- `以后我问复杂问题时，你应该先怎么回答？`
  - 能稳定命中 user preference recall
  - 不再被主线程 `clarification_required / next_step` 带偏

### 8.3 长场景验收

至少重跑：

- `memory-preference-and-cross-session-recall`
- `compound-task-decomposition-and-focus-return`
- `sixty-turn-real-user-marathon`

验收标准：

- 不能只看“是否崩溃”
- 要检查 recall 是否真正命中 durable path
- 要检查最终回答是否被 session/process governance text 污染

---

## 9. 最终取舍结论

这份清单的核心取舍是：

- 采用 Claude Code 的 `manifest + side-query recall + async extraction`
- 借 LangGraph 的状态分层思路
- 借 AutoGen 的协议化接口思路
- 保持 OpenAI guide 倡导的 centralized orchestration

但不引入新框架，不迁移主 runtime。

原因不是保守，而是因为当前问题已经明确落在现有代码边界上：

- recall 入口判别没有真正移交给 recall 子 agent
- session/process state 的 model-visible 边界还没收干净

把这两个边界切干净，当前系统就会更接近真正可维护的 Claude 式长期记忆架构。
