# 编排系统自由组合 Agent 配置、Intent Recognition Layer 与 Continuation Layer 重构方案

日期：2026-05-20  
状态：正式方案，首轮主链路已实施  
适用范围：OrchestrationSystem、Intent Recognition Layer、Continuation Layer、Single Agent Runtime、RuntimeLane、TaskGraph Coordination、QueryRuntime、TaskRunLoop、ContextResolver、TaskUnderstanding、AgentRuntimeChainAssembler、MemoryRuntimeView、Task Summary、PDF / Structured Data 子 Agent、RAG 检索、长期记忆召回、六十轮真实用户长跑

## 0. 结论

当前 follow-up 绑定问题不是某个规则缺了一条，而是执行态续接的职责还挂在旧的 state memory / session state 恢复链路上。系统已经逐步减少 state memory 对上下文装配的参与，但 `active_pdf`、`active_dataset`、`active_result_handle_id`、`active_subset_handle_id` 仍然通过 `restore_candidates`、`context_slots`、`resolved_bindings` 进入当前 turn，并参与任务理解、工具路由和子 Agent 委派。

这造成了一个结构性矛盾：用户希望 Agent 自己理解当前追问接续哪个对象，但系统却在运行层偷偷给了一个旧的显式绑定。最新六十轮长跑里 `turn 57` 已经暴露得很清楚：用户要求“按部门汇总这些人，只总结这前五名，不要扩展回全表”，系统表面走了 `delegate_to_agent`，但 `resolved_bindings` 里恢复的是 `active_pdf`，不是 `employees.xlsx`，子 Agent 随后继续被错误对象牵引。

本方案的核心方向不是单独修 follow-up，也不是新增一个“工厂层”，而是把职责放回现有编排系统：**Intent Recognition Layer 负责理解用户动作，编排系统根据 Agent 配置、RuntimeLane、Capability、Skill、Contract 自由组合运行模式，Continuation Layer 只在需要续接时提供候选、裁决、改写和契约，Agent Runtime / TaskGraph Coordination 分别承载不同执行形态**。

目标不是取消所有内部结构，而是不再让系统把 `active_dataset=xxx` 作为模型必须接受的答案，也不把 follow-up 当成唯一问题。系统先识别用户当前 turn 的意图动作：新任务、续接、切换、约束收紧、检索、记忆召回、子 Agent 委派、澄清或拒绝；只有当意图动作确实是续接时，才进入 Continuation Candidate / Decision / Contract 链路。

这套方案是通用方法，不是数据文件专用方案。PDF 和结构化数据只是最新长跑中暴露问题最集中的两个验证域。真正要落地的是一套可配置的 Continuation Layer：不同能力域通过 profile 声明候选类型、续接动作、改写规则、委派目标、返回契约和歧义策略，避免把 PDF / dataset 的判断逻辑硬编码进通用框架。

更准确地说，Continuation Layer 只是 Intent Recognition Layer 的一个下游动作模块。顶层要解决的是“用户这一句到底想让 Agent 做什么”，而不是只解决“用户这一句接着哪个旧对象”。如果没有这一层，系统会把很多本该识别为新任务、显式切换、记忆召回、范围约束或澄清请求的话，错误塞进 follow-up 追踪逻辑里。

同时还必须明确：**TaskGraph / Graph Run 是特定任务图编排模式，不是 Agent 处理长任务的唯一入口**。没有启动特定的多 Agent 协调任务时，主 Agent 仍然应该可以通过自己的 ReAct 循环、工具能力、task-local ledger、checkpoint、阶段提交、子 Agent 委派和验收机制完成用户需要的复杂任务。任务图只在需要固定流程、多角色协作、节点/边/阶段、并发调度、handoff 契约或可视化图式监控时启用。

### 0.1 核心定位：增强 Agent 判断力，而不是替代 Agent 判断

Intent Recognition Layer 的价值不在于“系统替 Agent 绑定正确对象”，而在于**增强 Agent 的判断力**。它要做的是把当前 turn 的用户意图、可用证据、候选对象、能力边界和冲突点整理成清晰、可比较、可审计的判断输入，让 Agent 基于用户原句、最近任务、工具结果、候选冲突和能力边界做自主裁决。

正确实现后，Agent 的判断过程应该从：

```text
在长历史、旧 state slot、隐式 active_* 绑定和工具残留里猜用户指什么
```

变成：

```text
先判断用户当前是在开启新任务、续接旧结果、显式切换对象、追加约束、召回记忆、请求检索、要求委派还是需要澄清；如果是续接，再在一组带来源、范围、置信度、冲突标记和可执行约束的候选中判断续接对象
```

因此，这套方法的第一性目标是 Agent cognition support，而不是 rule routing。intent frame、profile、candidate、contract、return 都只是认知支架：

1. intent frame 负责描述当前 turn 的意图假设、证据、冲突和动作选择，不把 route 当成意图。
2. profile 负责告诉系统“这个能力域有哪些可续接对象和边界”，不直接替 Agent 决定当前选谁。
3. candidate 负责把历史和执行结果整理成证据，不把证据伪装成结论。
4. decision 必须由主 Agent 结合当前用户意图输出，并说明理由。
5. contract 负责把 Agent 的裁决转成稳定执行输入，防止子 Agent 再次猜错。
6. return 负责把子 Agent 的执行结果回传给主 Agent，让主 Agent 收口和继续判断。

如果实现成 `active_dataset`、`active_pdf` 的新名字，或者 profile 直接决定当前 turn 的对象，这个方案就失败了。如果只是给 follow-up 多加几条规则，也是不够的。它必须让 Agent 先理解“用户想做什么”，再理解“需要接续什么”，最终做到看得更清楚、想得更准、问得更及时，而不是把 Agent 从判断链路里拿掉。

### 0.2 核心定位：编排系统自由组合 Agent 配置

编排系统本身就是自由组合 Agent 配置、能力、模式和约束的系统，不需要再额外抽象一个“工厂层”。这里的重点是把这种组装职责写清楚：用户请求不能被压成某个固定 route，而要由编排系统按需选择主 Agent、子 Agent、RuntimeLane、Capability、Skill、Contract、checkpoint 和验收方式。

正确的组装链路应该是：

```text
用户目标
  -> IntentDecision：用户想做什么、边界是什么、复杂度和风险是什么
  -> 编排系统：选择/组合 AgentRuntimeProfile、RuntimeLane、Capability、Skill、Contract
  -> RuntimeAssembly / IntentActionPlan：交给对应 runtime 的运行装配结果
  -> Runtime：单 Agent 执行、后台单 Agent、专门子 Agent、RAG answer、TaskGraph coordination 等
  -> Structured Return / Committed Output：主 Agent 收口并继续对话
```

这意味着：

1. 主 Agent 是默认的任务处理主体，不应因为没有任务图就只能做短回答。
2. 子 Agent 是隔离上下文、专业化能力和并行工作的手段，不是把主 Agent 思考能力外包掉。
3. TaskGraph 是固定流程和多 Agent 协调的生产线，不是所有长任务的生产线。
4. RuntimeLane 负责同步/异步、权限、checkpoint、恢复和进度事件，不重新解释用户意图。
5. Capability / Skill / Agent profile 是可组合部件，不能把某个业务场景写死在核心编排代码里。

### 0.3 主 Agent 长任务与 TaskGraph 的边界

需要把“长任务”和“图任务”拆开看：

| 类型 | 含义 | 运行形态 |
|---|---|---|
| 主 Agent 长任务 | 一个 Agent 可以自主完成，但需要多步计划、工具观察、阶段提交、自检和恢复 | `single_agent_long_run` |
| 后台单 Agent 长任务 | 一个 Agent 可以完成，耗时长或不需要阻塞当前回复 | `single_agent_background_run` |
| 专业子 Agent 长任务 | 某个领域 Agent 长时间处理一个 bounded 子任务 | `specialist_subagent_long_run` |
| TaskGraph 协调任务 | 多角色、多节点、阶段、边、handoff、并发或图式验收 | `graph_coordination_run` |

所以，`Graph Run` 的触发条件不是“任务很长”，而是“需要图式协调”。普通复杂任务应该优先让主 Agent 进入可恢复的长任务循环；只有用户目标或系统 profile 明确需要多 Agent 图协调时，才编译或恢复 TaskGraph。

---

## 1. 最新失败证据

### 1.1 测试结果

最新长跑产物：

```text
output/test_runs/rerun-20260519-60turn/run_result.json
output/test_runs/rerun-20260519-60turn/issues.json
```

结果：

```text
45/53 user turns passed
first failure turn = 11
duration_ms = 2946176.66
terminal_event = scenario_failed
```

相比上一轮：

```text
已修复旧失败：turn 3、turn 4、turn 8
新增失败：turn 44、turn 47、turn 53
仍失败：turn 11、turn 13、turn 25、turn 52、turn 57
```

这说明后台记忆重建阻塞已经不再是主要矛盾，当前问题集中在后半段复杂续接、跨会话回忆和数据/PDF 切换。

### 1.2 失败分类

| 类型 | 失败 turn | 表现 |
|---|---:|---|
| 数据集续接失败 | 11、13、44、47、57 | `active_dataset` 没建立或被 PDF 覆盖，部分 turn 没按预期委派子 Agent |
| 长期偏好记忆没召回 | 25、52 | `memory_read` 被调用，但没有召回“岩”这个称呼偏好 |
| 信息不足表达没命中断言 | 53 | 语义接近正确，但没有命中“缺什么 / 先明确 / 不要直接猜 / 承认不足 / 澄清边界”等检查词 |

### 1.3 最关键证据：turn 57

`turn 57` 的用户请求是：

```text
按部门汇总这些人，只总结这前五名，不要扩展回全表。
```

系统计划：

```text
plan.route = tool
plan.tool = delegate_to_agent
recipe_id = runtime.recipe.structured_data_analysis
```

但当前 turn 的 `resolved_bindings` 仍是：

```json
{
  "binding_id": "binding:state:active_pdf:knowledge-ai-knowledge-2025年ai治理报告-回归现实主义-pdf",
  "file_kind": "pdf",
  "source": "session_state",
  "metadata": {
    "slot_name": "active_pdf",
    "path": "knowledge/AI Knowledge/2025年AI治理报告：回归现实主义.pdf"
  }
}
```

这不是子 Agent 单独犯错，而是上游续接裁决已经给错了证据。它把“这些人 / 前五名”这类数据结果续接，恢复成了 PDF 文档上下文。

---

## 2. 问题定义

### 2.1 当前破坏的系统属性

系统缺少一个独立的“当前 turn 意图识别层”。过去 state memory、TaskUnderstanding、ContextResolver、RuntimeLoop 同时承担了多种职责：

1. 记录会话状态和长期事实。
2. 为上下文装配提供可恢复内容。
3. 判断用户当前是否在追问旧对象。
4. 为当前 turn 执行绑定 PDF、数据集、结果子集或任务结果。
5. 推断工具路由、子 Agent 委派和 RAG / memory / direct tool 的执行方式。

现在 state memory 已经不再适合作为上下文装配的主入口，但“当前 turn 意图裁决”没有被新机制接住，导致 `ContextResolver` 和 `TaskUnderstanding` 仍通过旧槽位恢复做当前 turn 裁决，`RuntimeLoop` 又根据 route / capability / active_constraints 二次推断执行对象。

真正破坏的系统属性不是“少了一个 follow-up 规则”，而是：

1. **意图、对象、路由、记忆和执行约束没有分层。**
2. **route 被过早当成 intent，导致 `rag`、`pdf`、`structured_data` 这种执行路径污染用户意图理解。**
3. **restore 被误当成 decide，旧 `active_*` slot 可以覆盖当前用户语义。**
4. **主 Agent 缺少一个可解释的意图判断输入，只能在长历史、工具残留和隐式绑定中猜。**
5. **子 Agent 收到的是执行片段，不是主 Agent 明确裁决后的工作意图。**

### 2.2 正确终态

正确终态应该满足：

1. 用户当前 turn 的意图动作由 Agent 在 Intent Recognition Layer 中裁决，而不是由旧槽位、route hint 或工具残留决定。
2. 系统提供的是意图假设和候选证据集，不是唯一绑定答案。
3. follow-up 的接续对象由 Agent 根据候选证据自主判断，而不是系统直接指定。
4. 当前 turn 的裁决结果必须结构化，供工具路由、子 Agent 委派和最终回答收口使用。
5. 长期记忆只负责用户偏好、稳定约定、项目事实等可回忆知识，不承担执行态续接。
6. PDF / dataset / task result / bundle result 的续接都走同一套候选、裁决、改写和回传协议。
7. 新能力域不需要修改核心裁决代码，只需要增加或调整 intent / continuation profile。
8. Intent Layer 必须能识别“不是续接”的情况，例如新任务、显式切换、记忆召回、检索请求、约束收紧、澄清、拒绝和多能力组合。

### 2.3 Intent Layer 要识别的动作类型

第一批动作类型：

| intent_action | 含义 | 是否进入 Continuation |
|---|---|---|
| `start_new` | 用户开启新任务或新问题 | 否 |
| `continue` | 用户追问上一轮对象、结果、子集或任务 | 是 |
| `switch_target` | 用户显式切换到另一个文件、任务、节点、知识源或页面 | 可生成新 candidate，但不是旧对象续接 |
| `refine_scope` | 用户收紧或补充当前结果范围，例如“只看前五名”“不要扩展回全表” | 是，且必须产生 scope contract |
| `recall_memory` | 用户询问偏好、约定、项目事实或长期记忆 | 否，进入 memory_fact recall |
| `retrieve_knowledge` | 用户要求从本地知识库、RAG、web 或官方来源检索 | 否，进入检索意图 |
| `delegate_work` | 用户要求让子 Agent / 专家 / 工具执行具体工作 | 视对象是否续接决定 |
| `clarify` | 用户表达不完整，或系统证据冲突需要追问 | 否，先澄清 |
| `reject_or_boundary` | 用户请求越界、证据不足、能力不支持或不应执行 | 否，说明边界 |
| `compound` | 同一句包含多个动作，例如“换成 X，再按 Y 总结” | 拆成有序 intent steps |

这层不是把所有东西都规则化。它的作用是让 Agent 先有一张“当前用户动作地图”，再决定是否需要调用 continuation、memory、retrieval、tool、sub-agent 或 clarification。

---

## 3. 当前系统源码报告

### 3.1 QueryRuntime 已经不是主要问题

`backend/query/runtime.py` 现在是较薄的 API adapter。它负责：

```text
QueryRuntime.astream()
  -> build turn_id / task_id
  -> analyze_memory_intent()
  -> TaskRunLoop.run_single_agent_stream()
  -> assistant_message_committer()
```

这符合之前“QueryRuntime 不再拥有规划、工具路由、worker 编排”的改造方向。follow-up 问题不应该回退到 QueryRuntime 里补规则。

### 3.2 ContextResolver 仍在消费 state snapshot 槽位

`backend/context_management/resolver.py` 当前会从 `memory_runtime_view.state_snapshot.context_slots` 读取：

```text
active_pdf
committed_pdf
active_dataset
committed_dataset
active_object_handle_id
active_result_handle_id
active_subset_handle_id
active_constraints
```

然后创建 `ResolvedBinding`：

```text
binding:state:active_pdf:...
binding:state:active_dataset:...
```

这就是 `turn 57` 中 stale PDF 进入结构化上下文的直接来源。

### 3.3 TaskUnderstanding 仍依赖 active_bindings 规则

`backend/understanding/task_understanding.py` 当前通过 `active_bindings` 收集：

```text
bound_dataset_path
bound_pdf_path
followup_target_kind
followup_scope
```

并通过 `_resolve_followup_target()` 判断：

```text
active_subset
active_dataset
active_pdf
bundle_ordinals
```

这种方式本质上还是“先恢复一个绑定，再按规则套意图”。它会在 PDF 和 dataset 交替出现时把旧对象误带入当前 turn。

### 3.4 TaskRunLoop 仍在写回 active_* 约束

`backend/orchestration/runtime_loop/task_run_loop.py` 中仍有多处将工具观察投影为：

```text
active_pdf
active_dataset
followup_mode = binding_ref
followup_binding_key = active_pdf / active_dataset
followup_target_task_id
```

这些字段可以作为候选证据来源，但不应再直接作为当前 turn 的权威绑定。

### 3.5 现有测试已承认 result-level follow-up，但机制仍不完整

`backend/tests/agent_main_assembly_semantic_boundary_regression.py` 已经有一条很接近目标的测试：

```text
test_active_subset_followup_is_result_level_contract
```

它验证了：

```text
followup_target_kind = active_subset
constraint_policy = result_subset_only_do_not_expand_to_full_object
active_subset_handle_id = subset:selection:employees:top5
```

但真实长跑 `turn 57` 证明：当 state snapshot 中同时存在旧 PDF 与数据结果时，候选选择仍会被旧 slot 污染。

---

## 4. 外部方法参考

### 4.1 Dialogue State Tracking

参考：

- ["Do you follow me?": A Survey of Recent Approaches in Dialogue State Tracking](https://arxiv.org/abs/2207.14627)

可借鉴点：

1. Follow-up 本质上是“根据历史追踪当前用户需求”的问题。
2. 状态追踪的结果会影响下游策略，不应只作为 prompt 背景。
3. 现代 DST 不一定是传统 slot filling，可以用 text-to-text 或结构化语义状态。

本系统不直接复制 DST 的 slot 模型，因为我们不想回到 `active_dataset` 硬槽位；但要借鉴它“先追踪当前需求，再决定下游动作”的层级边界。

### 4.2 Conversational Query Rewriting

参考：

- [CONQRR: Conversational Query Rewriting for Retrieval with Reinforcement Learning](https://arxiv.org/abs/2112.08558)

可借鉴点：

1. 会话中的问题经常不是独立问题。
2. 检索或工具执行前，应先把省略句改写成独立、可执行的问题。
3. 改写应服务下游检索/工具，而不是只追求语言自然。

对应到本系统：

```text
用户原句：按部门汇总这些人，只总结这前五名，不要扩展回全表。

目标改写：
基于上一轮 employees.xlsx 结果中薪资最高的前五名员工，
只在该五人子集内按部门归类总结，不读取或统计全表。
```

### 4.3 Intent-aware Agent Memory

参考：

- [Grounding Agent Memory in Contextual Intent](https://arxiv.org/abs/2601.10702)
- [OpenReview PDF](https://openreview.net/pdf?id=7FigeE9Zyl)

可借鉴点：

1. 长程 Agent 里，相似实体和事实会在不同目标下反复出现。
2. 只按语义相似度召回会把 context-mismatched evidence 带进来。
3. 记忆或历史片段应带有 contextual intent，包括目标段、动作类型、关键实体类型。
4. 检索时先按 intent compatibility 过滤，再排序。

对应到本系统：

```text
PDF 和 employees.xlsx 都可能在近期出现。
“这些人 / 前五名 / 按部门”对应 action_type=structured_data_aggregation，entity_type=employee。
它不应匹配 action_type=pdf_page_review，entity_type=document_page 的旧 PDF 证据。
```

### 4.4 LangGraph Memory / Persistence

参考：

- [LangGraph Memory](https://docs.langchain.com/oss/python/langgraph/add-memory)
- [LangGraph Persistence](https://docs.langchain.com/oss/python/langgraph/persistence)

可借鉴点：

1. thread state 和 long-term memory 是两类不同机制。
2. 短期线程态用于当前运行连续性，长期记忆用于跨会话知识。
3. checkpoint / store 的边界要清楚，否则恢复状态会污染长期事实或当前执行。

对应到本系统：

```text
state memory / session memory / durable memory 不应继续混合承担 follow-up 续接。
Continuation Layer 是当前执行态推理层，不是长期记忆层。
```

### 4.5 长任务 Agent 编排参考

参考：

- [ReAct: Synergizing Reasoning and Acting in Language Models](https://arxiv.org/abs/2210.03629)
- [Tree of Thoughts: Deliberate Problem Solving with Large Language Models](https://arxiv.org/abs/2305.10601)
- [Reflexion: Language Agents with Verbal Reinforcement Learning](https://arxiv.org/abs/2303.11366)
- [Voyager: An Open-Ended Embodied Agent with Large Language Models](https://arxiv.org/abs/2305.16291)
- [OpenAI Agents SDK - Multi-agent orchestration](https://openai.github.io/openai-agents-python/multi_agent/)
- [AutoGen AgentChat](https://autogenhub.github.io/autogen/docs/Use-Cases/agent_chat/)

可借鉴点：

1. ReAct 的核心不是“先分类再执行”，而是让模型在 reasoning 和 acting 之间循环，意图层不能切断这个循环。
2. Tree of Thoughts 说明复杂任务需要多路径探索、评估和回退，意图层应能把复杂请求升级为单 Agent 长任务、后台 Agent 长任务或任务图协调，而不是压成单步 route。
3. Reflexion 说明长任务需要失败反馈、反思摘要和下一轮策略更新，意图层应接收运行反馈形成新的 intent hypothesis。
4. Voyager 的 automatic curriculum / skill library 说明长任务能力来自目标分解、技能积累和自验证，不是每一轮重新从零判断。
5. OpenAI Agents SDK 和 AutoGen 都把 handoff / manager-specialist / conversation orchestration 作为一等能力；我们的 Intent Layer 应负责选择协作模式，但不能替代 specialist 的执行。
6. LangGraph 的 persistence / checkpoint / interrupt 提醒我们：长任务执行力来自可恢复状态机，而不是把所有历史塞给主 Agent。

对应到本系统：

```text
Intent Layer 负责判断当前 turn 是否应该：
  - 直接回答
  - 进入 ReAct 单轮工具循环
  - 升级为单 Agent 长任务
  - 升级为后台单 Agent 长任务
  - 升级为 Graph Run 多 Agent / 任务图协调
  - 委派同步/异步子 Agent
  - 触发 checkpoint/resume
  - 进入人工确认或澄清

但真正执行长任务的是 Agent Runtime / RuntimeLane / Checkpoint / Handoff Contract；
Graph Run 只负责多 Agent 或图式协调任务，
不是 Intent Layer 自己。
```

### 4.6 设计原则映射

本地设计原则中也有相同方向：

- `docs/设计原则/12-Agent-系统.md`
  - 子 Agent 应隔离上下文，完成后返回精炼结果，避免主上下文污染。
- `docs/设计原则/23-Memory系统.md`
  - 记忆分层，Relevant Memories 按需召回，不把所有记忆直接塞入上下文。
  - Auto Memory 保存的是稳定知识，Session Memory 保存的是当前会话结构化笔记。

本方案延续这些原则：续接不是长期记忆；子 Agent 不能靠主上下文里的模糊状态猜对象；主 Agent 需要拿到结构化回传再收口。

---

## 5. 推荐设计方向

### 5.1 总体路线

采用“Intent Recognition Layer 判断用户动作，编排系统自由组合执行能力，Continuation Layer 专管续接”的分层路线：

```text
用户原句 / recent turns / task summary / memory hints / tool projections
  -> IntentSignalCollector
  -> IntentHypothesisBuilder
  -> 主 Agent IntentDecision
  -> OrchestrationSystem capability / runtime assembly
      -> start_new: normal planning
      -> continue/refine_scope: Continuation Layer
      -> switch_target: explicit target resolution
      -> recall_memory: memory recall
      -> retrieve_knowledge: RAG / web / official retrieval
      -> delegate_work: sub-agent contract when needed
      -> execution_strategy: direct / react / single-agent long / background / specialist / graph coordination
      -> clarify/reject: answer boundary
  -> main agent / tool / sub-agent / graph execution
  -> structured return
  -> main answer closure
```

这条链路的关键是：系统收集信号和候选，Agent 先裁决“当前用户想做什么”，再裁决“如果需要续接，应该续接什么”。

更关键的是：**IntentDecision 不等于执行方案**。IntentDecision 只描述用户动作和边界；现有编排系统负责把当前任务组装成合适的运行形态。没有任务图时，主 Agent 仍然可以通过自己的 runtime、工具、skills、checkpoint 和反思验收来处理复杂任务；任务图只是当任务需要固定流程、多 Agent 协调或图式调度时才启用。

### 5.2 明确不采用的路线

| 路线 | 不采用原因 |
|---|---|
| 继续扩展 `active_pdf / active_dataset` 规则 | 会把旧 slot 机制越补越复杂，PDF 与 dataset 切换仍容易串 |
| 只做 Continuation Layer | 会把新任务、切换、检索、记忆召回、澄清都误塞进 follow-up 问题 |
| 完全让模型裸猜 | 长上下文和多会话场景下容易丢对象，子 Agent 也无法拿到稳定工作包 |
| 把 state memory 重新放回上下文装配 | 会回到记忆与执行态混用的问题 |
| 只改 prompt | 不能保证工具路由、子 Agent 输入和回传结构一致 |
| 让 route hint 充当 intent | `rag`、`pdf`、`structured_data` 是执行路径，不是用户意图，会让执行层歪 |
| 把长任务默认升级为任务图 | 会削弱主 Agent 自主处理复杂任务的能力，把“长”误解成“多 Agent 图协调” |

### 5.3 采用的折中

不把绑定作为系统答案直接塞给模型；但保留内部意图信号、候选、句柄、来源和置信信息。Agent 自主选择，执行层验证选择是否可执行。

Intent Layer 使用可解释结构增强判断，但不把 profile 或规则变成最终裁判：

1. 规则和 profile 只生成 intent hypotheses。
2. 主 Agent 输出 IntentDecision，并给出理由和不确定性。
3. 编排系统根据 IntentDecision、能力注册表、RuntimeLane、AgentRuntimeProfile、CapabilityUnit 和任务上下文组装执行方案。
4. Runtime 只执行编排系统产出的 RuntimeAssembly / IntentActionPlan，不再绕过意图裁决自行读取 `active_*`。
5. Continuation 只处理 `continue` / `refine_scope` / 部分 `delegate_work`，不能吞掉所有复杂语义。

### 5.4 执行力保护原则

Intent Layer 必须增强执行力，而不是削弱执行力。它不能变成“每次都先让模型做分类、再等系统批准”的阻塞层，也不能把复杂任务压扁成单步 route。

硬性原则：

1. **Intent is not Route**：`start_new / continue / refine_scope / retrieve_knowledge / delegate_work / compound` 是用户动作；`rag / pdf / structured_data / task_graph / tool / memory` 是执行路径。
2. **Decide Before Execute, Do Not Over-Decide**：意图层只做执行模式选择和边界确认，不替工具、子 Agent、任务图节点做专业执行。
3. **Short Task Fast Path**：低风险、显式、单步请求可以走 deterministic fast path，不必每次调用裁决模型。
4. **Single Agent Can Be Long-Running**：长任务不等于 Graph Run。单 Agent 也必须具备长时间规划、执行、观察、反思、恢复和提交产物的能力。
5. **Graph Run Is Coordination, Not Length**：只有需要多 Agent 协作、显式节点/边/阶段、跨角色 handoff、并行调度或图式验收时，才升级为 Graph Run。
6. **ReAct Loop 保留**：进入执行后，Agent 仍应能观察结果、调整下一步、再次行动；IntentDecision 只约束目标和边界，不锁死每一步。
7. **Checkpoint First**：长任务每个阶段必须有 checkpoint / handoff packet / committed output ref，不能依赖主上下文记住进度。
8. **Async by Default for Management Work**：计划管理、记忆维护、索引重建、长任务监控应后台异步，不阻塞用户主 turn。
9. **Human Gate Only When Needed**：只有权限、破坏性操作、重大范围变更或证据冲突时才要求澄清/确认。

### 5.5 长任务能力分层

意图感知层要服务长任务，但不能自己变成长任务执行器。合理分层如下：

| 层级 | 作用 | 典型输出 | 不能做什么 |
|---|---|---|---|
| Intent Recognition Layer | 判断用户动作、复杂度、风险、是否需要长任务 | `IntentDecision`、`IntentActionPlan` | 不能执行节点业务 |
| Single Agent Runtime | 承载单 Agent 的长任务循环、工具调用、阶段提交和恢复 | agent run handle、step checkpoint、committed output | 不能擅自拆成多 Agent 图 |
| Background Agent Runtime | 承载不阻塞主 turn 的单 Agent 长任务 | progress event、async agent result | 不能污染主 Agent 当前上下文 |
| Graph Run / Coordination Layer | 承载多 Agent、图节点/边、阶段、并行和 handoff 协调 | `TaskGraphRuntimeSpec`、`ContractManifest`、coordination run | 不能取代单 Agent 长任务 |
| RuntimeLane / Scheduler | 调度同步/异步、并发/顺序、checkpoint/resume | dispatch plan、node run state | 不能重新解释用户目标 |
| Agent Execution Loop | 在单 Agent 或节点内 ReAct 执行，调用工具和子 Agent | tool results、node output | 不能越过 contract 扩大范围 |
| Reflection / Acceptance Layer | 检查结果、记录失败、生成修正策略 | acceptance result、reflection note | 不能把未提交草稿当最终产物 |
| Memory / Skill Layer | 沉淀稳定偏好、技能、经验和可复用策略 | durable fact、skill ref | 不能承担当前 turn 执行绑定 |

### 5.6 编排能力选择策略

IntentActionPlan 需要能表达执行模式，而不是只有 route：

| execution_strategy | 适用场景 | 编排方式 |
|---|---|---|
| `direct_answer` | 简短问答、无需工具 | 主 Agent 直接回答 |
| `single_react_loop` | 单轮可完成但需要工具观察 | 主 Agent 工具循环 |
| `single_agent_long_run` | 单 Agent 可完成但需要多步规划、阶段提交或长时间工具执行 | 单 Agent run handle + step checkpoints |
| `single_agent_background_run` | 单 Agent 可后台执行的长任务 | 后台 Agent lifecycle + progress notification + checkpoint |
| `retrieval_augmented_answer` | 需要本地 RAG / web / official source | 检索 contract + answer synthesis |
| `specialist_handoff` | 需要 PDF、数据、代码、浏览器等专门能力 | 主 Agent 委派子 Agent，子 Agent 结构化回传 |
| `specialist_subagent_long_run` | 需要某个专业子 Agent 长时间处理 | 子 Agent run handle + specialist checkpoint |
| `graph_coordination_run` | 需要多 Agent、任务图、并行节点、显式 handoff 或跨阶段协调 | TaskGraph compile + scheduler + checkpoint |
| `human_gate` | 证据冲突、权限风险、破坏性操作 | 澄清/确认后继续 |

### 5.7 编排系统：自由组合 Agent 配置和运行模式

编排系统不是一个新层，而是现有 OrchestrationSystem 的核心职责。它不替 Agent 思考，也不固定任务图；它根据用户意图、能力注册、运行上下文和风险边界，选择这次任务应组合哪些 Agent 配置、工具能力、RuntimeLane、Skill、Contract 和 checkpoint。

它要能自由组合以下部件：

| 部件 | 作用 | 示例 |
|---|---|---|
| Agent body | 谁来做 | main agent、pdf agent、data agent、code agent |
| Runtime mode | 怎么跑 | interactive、single_agent_long、background、graph_coordination |
| Tool / capability unit | 用什么能力 | RAG、PDF、structured data、browser、shell、workspace |
| Skill / prompt profile | 怎么指导 Agent | RAG 工作流、数据分析工作流、代码审计工作流 |
| Memory scope | 读写什么记忆 | none、session notes、durable facts、task-local ledger |
| Contract package | 输入输出边界 | input、output、handoff、return、acceptance |
| Checkpoint policy | 怎么恢复 | none、step checkpoint、agent lifecycle checkpoint、graph checkpoint |
| Acceptance policy | 怎么收口 | self-check、specialist return validation、stage gate |

决策不是“长任务就任务图”，而是：

```text
用户意图 + 任务复杂度 + 所需能力 + 是否多角色 + 是否固定流程 + 是否需要并发/阶段/handoff
  -> 选择运行模式
  -> 组装 RuntimeAssembly / IntentActionPlan
  -> 交给对应 runtime
```

模式边界：

| 模式 | 何时使用 | 不应使用 |
|---|---|---|
| `single_agent_long_run` | 主 Agent 自己能完成，虽然需要多步、长时间、工具观察和阶段提交 | 不需要多角色时不要拆任务图 |
| `single_agent_background_run` | 主 Agent/单个 Agent 能完成，但耗时长、可后台、需进度通知 | 不要阻塞交互 turn |
| `specialist_handoff` | 单个专门 Agent 更适合处理一个 bounded 子任务 | 不要把主任务完全外包给子 Agent |
| `specialist_subagent_long_run` | 专门 Agent 需要长时间处理自己的领域任务 | 不要升级为多 Agent 图，除非有多角色协调 |
| `graph_coordination_run` | 明确需要多 Agent、节点/边、阶段、并发、handoff 或固定流程 | 不要用它替代主 Agent 自主工作能力 |

主 Agent 长任务装配示例：

```json
{
  "intent_decision_ref": "intent:decision:...",
  "execution_strategy": "single_agent_long_run",
  "runtime_lane": "single_agent_long",
  "agent_profile_id": "main_interactive_agent",
  "capability_units": ["workspace_read", "workspace_write", "shell", "rag"],
  "skill_profiles": ["codebase_investigation", "implementation_with_verification"],
  "memory_scope": {
    "read": ["session_notes", "durable_relevant_facts"],
    "write": ["task_local_ledger", "durable_fact_candidates"]
  },
  "contracts": {
    "input_contract_id": "contract.intent.input.general_task",
    "output_contract_id": "contract.agent.output.committed_summary",
    "acceptance_contract_id": "contract.acceptance.self_verified"
  },
  "checkpoint_policy": "step_checkpoint",
  "acceptance_policy": "self_check_then_commit",
  "progress_policy": "stream_progress_to_main_thread"
}
```

Graph coordination 的装配结果应显式不同：

```json
{
  "intent_decision_ref": "intent:decision:...",
  "execution_strategy": "graph_coordination_run",
  "runtime_lane": "graph_coordination",
  "graph_profile_id": "task_graph.multi_agent_review_merge",
  "agent_profiles": ["planner_agent", "worker_agent", "review_agent"],
  "contracts": {
    "graph_contract_id": "contract.graph.review_merge",
    "handoff_contract_id": "contract.handoff.agent_to_agent",
    "acceptance_contract_id": "contract.acceptance.stage_gate"
  },
  "checkpoint_policy": "event_checkpoint_spine",
  "acceptance_policy": "stage_acceptance_gate"
}
```

这两个装配结果都可以是长任务，但只有第二个是任务图协调。

### 5.8 主 Agent 自主工作能力

主 Agent 不应该因为没有任务图就失去处理复杂任务的能力。它至少需要具备：

1. 自主规划：把用户目标拆成内部步骤，但不一定创建任务图。
2. 工具循环：按 ReAct 方式读取、执行、观察、调整。
3. 上下文维护：用 task-local ledger / summary refs / committed outputs 记录进展。
4. 阶段提交：对长任务产生可审计的中间结果。
5. 自检与修正：失败后能反思、改计划、重试。
6. 可恢复：长任务要能从 run handle / checkpoint 恢复，而不是靠对话历史硬记。
7. 可委派：需要专门能力时委派子 Agent，但主 Agent 仍负责收口。

任务图的职责是“固定流程、多角色、强协调、可视化调度”，不是“让 Agent 才能做长任务”。

配置示例：

```json
{
  "intent_profile_id": "intent.long_task.execution_mode",
  "matched_actions": ["compound", "delegate_work", "start_new"],
  "complexity_thresholds": {
    "min_steps_for_long_run": 3,
    "min_distinct_agents_for_graph_run": 2,
    "requires_checkpoint_after_minutes": 2,
    "requires_acceptance_gate_when_outputs": ["file", "artifact", "memory_commit"]
  },
  "execution_strategy_candidates": [
    "single_agent_long_run",
    "single_agent_background_run",
    "graph_coordination_run",
    "specialist_handoff"
  ],
  "allowed_runtime_lanes": ["interactive", "single_agent_long", "background", "graph_coordination"],
  "requires_contracts": [
    "input_contract",
    "output_contract",
    "handoff_contract",
    "acceptance_contract"
  ],
  "fallback_strategy": "clarify_or_plan_before_execute"
}
```

---

## 6. 目标架构

### 6.1 新增核心对象

目标架构不新增“编排工厂层”。新增对象只服务两件事：第一，给主 Agent 更清晰的意图判断输入；第二，让现有编排系统可以根据 IntentDecision 稳定组合 Agent 配置、RuntimeLane、Capability、Skill 和 Contract。否则 IntentDecision 仍然会被下游 runtime 临时解释，系统会再次滑回 route hint、active binding 和工具分支散落的状态。

核心对象分三组：

| 分组 | 对象 | 职责 |
|---|---|---|
| 意图认知 | `IntentFrame`、`IntentHypothesis`、`IntentDecision` | 帮主 Agent 判断用户当前想做什么 |
| 编排组装 | `IntentActionPlan`、`RuntimeAssembly`、`RuntimeLaneProfile`、`AgentRuntimeProfile`、`CapabilityUnit`、`OrchestrationProfile` | 由现有编排系统组合 Agent 能力、运行模式、权限、契约和恢复策略 |
| 续接执行 | `ContinuationCandidate`、`ContinuationDecision`、`ContinuationExecutionContract`、`ContinuationReturn` | 只处理 continue / refine_scope 的对象、范围、改写和回传 |

#### IntentFrame

表示当前 turn 的意图识别输入视图。它不是最终结论，而是给 Agent 判断用的证据包。

```json
{
  "frame_id": "intent:frame:...",
  "user_message": "按部门汇总这些人，只总结这前五名，不要扩展回全表。",
  "recent_goal_summary": "上一轮找出了 employees.xlsx 薪资最高的前五名员工。",
  "explicit_targets": [],
  "intent_signals": [
    {
      "signal_type": "anaphora",
      "text": "这些人",
      "suggested_actions": ["continue", "refine_scope"]
    },
    {
      "signal_type": "scope_constraint",
      "text": "只总结这前五名，不要扩展回全表",
      "suggested_actions": ["refine_scope"]
    }
  ],
  "candidate_summary": {
    "continuation_candidate_count": 2,
    "memory_fact_candidate_count": 0,
    "retrieval_candidate_count": 0,
    "domain_conflicts": ["pdf_candidate_conflicts_with_people_subset_language"]
  }
}
```

#### IntentHypothesis

系统基于信号生成的候选意图。它只能作为 Agent 判断输入，不能直接驱动执行。

```json
{
  "hypothesis_id": "intent:hyp:continue:employees-top5",
  "intent_action": "continue",
  "target_domain": "dataset",
  "supporting_signals": ["这些人", "前五名", "按部门"],
  "conflicting_signals": [],
  "candidate_refs": ["cont:cand:employees-top5"],
  "confidence": 0.84,
  "reason": "指代词和范围约束都指向上一轮结构化数据结果子集。"
}
```

#### IntentDecision

主 Agent 对当前 turn 的顶层意图裁决。

```json
{
  "decision_id": "intent:decision:...",
  "primary_action": "refine_scope",
  "secondary_actions": ["continue", "delegate_work"],
  "selected_hypothesis_ids": ["intent:hyp:continue:employees-top5"],
  "reason": "用户没有开启新任务，而是在上一轮前五名员工结果内追加按部门汇总要求，并明确禁止回到全表。",
  "requires_continuation": true,
  "requires_memory": false,
  "requires_retrieval": false,
  "requires_clarification": false,
  "task_complexity": "single_step | multi_step | long_running",
  "execution_strategy": "specialist_handoff",
  "runtime_lane": "interactive",
  "requires_checkpoint": false,
  "requires_acceptance_gate": true,
  "confidence": 0.91,
  "ambiguities": []
}
```

#### IntentActionPlan

把 IntentDecision 转成运行时可执行计划，但仍不替代具体工具或子 Agent 的业务执行。

```json
{
  "plan_id": "intent:plan:...",
  "decision_ref": "intent:decision:...",
  "steps": [
    {
      "step_id": "intent:step:continuation",
      "action": "continue",
      "module": "continuation",
      "execution_strategy": "specialist_handoff",
      "runtime_lane": "interactive",
      "input_refs": ["cont:cand:employees-top5"],
      "expected_output": "continuation.execution_contract"
    },
    {
      "step_id": "intent:step:delegate",
      "action": "delegate_work",
      "module": "sub_agent",
      "execution_strategy": "specialist_handoff",
      "runtime_lane": "interactive",
      "input_refs": ["continuation.execution_contract"],
      "expected_output": "continuation.return"
    }
  ],
  "checkpoint_policy": "none | step_checkpoint | agent_lifecycle_checkpoint | graph_checkpoint",
  "acceptance_policy": "basic_return_validation"
}
```

#### RuntimeAssembly

`RuntimeAssembly` 表示现有编排系统根据 IntentDecision 组合出的运行装配结果。它不是一个新系统层，也不是 prompt，更不是工具调用脚本；它只是把“谁来做、怎么跑、能用什么、边界是什么、如何恢复、如何验收”以结构化形式交给 TaskRunLoop / runtime assembly builder。

```json
{
  "assembly_id": "runtime-assembly:single-agent-long:...",
  "authority": "orchestration.runtime_assembly",
  "intent_decision_ref": "intent:decision:...",
  "execution_strategy": "single_agent_long_run",
  "runtime_lane": "single_agent_long",
  "agent_profile_id": "main_interactive_agent",
  "capability_units": ["workspace_read", "workspace_write", "shell", "rag"],
  "skill_profiles": ["codebase_investigation", "implementation_with_verification"],
  "memory_scope": {
    "read": ["session_notes", "durable_relevant_facts"],
    "write": ["task_local_ledger", "durable_fact_candidates"]
  },
  "contracts": {
    "input_contract_id": "contract.intent.input.general_task",
    "output_contract_id": "contract.agent.output.committed_summary",
    "acceptance_contract_id": "contract.acceptance.self_verified"
  },
  "checkpoint_policy": "step_checkpoint",
  "progress_policy": "stream_progress_to_main_thread",
  "acceptance_policy": "self_check_then_commit"
}
```

硬性约束：

1. `RuntimeAssembly` 由现有编排系统根据 IntentDecision 和 profile 组合生成，不能由 Intent parser 直接拼出来。
2. Runtime assembly 可以表示主 Agent 工作、子 Agent 工作、后台工作或 TaskGraph 工作，但这些是不同 execution_strategy。
3. Runtime assembly 只描述运行边界和契约，不替 Agent 写死每一步工具脚本。
4. Runtime 只消费 runtime assembly，不再自行从旧 `active_*`、route hint 或 state snapshot 中补目标。

#### RuntimeLaneProfile

`RuntimeLaneProfile` 定义一次工作怎么被调度，而不是定义做什么。

```json
{
  "lane_id": "single_agent_long",
  "authority": "orchestration.runtime_lane_profile",
  "dispatch_mode": "foreground_streaming",
  "async_policy": "non_blocking_for_management_work",
  "checkpoint_policy": "step_checkpoint",
  "resume_policy": "resume_from_run_handle",
  "progress_event_policy": "emit_stage_and_tool_events",
  "permission_surface": "main_agent_allowed_tools_with_contract_limits",
  "max_runtime_seconds": 1800
}
```

运行 lane 的职责边界：

1. `interactive` 适合短任务、同步工具循环和有界 handoff。
2. `single_agent_long` 适合主 Agent 长任务，不需要任务图。
3. `background` 适合后台单 Agent 或专门子 Agent 长任务。
4. `graph_coordination` 只适合 TaskGraph coordination。
5. lane 只能调度和恢复，不能重新解释用户目标。

#### AgentRuntimeProfile

`AgentRuntimeProfile` 定义一个 Agent 作为执行主体时的能力边界。

```json
{
  "agent_profile_id": "main_interactive_agent",
  "authority": "orchestration.agent_runtime_profile",
  "agent_role": "main_agent",
  "supports_execution_strategies": [
    "direct_answer",
    "single_react_loop",
    "single_agent_long_run",
    "single_agent_background_run",
    "specialist_handoff"
  ],
  "supports_checkpoint": true,
  "supports_task_local_ledger": true,
  "supports_subagent_delegation": true,
  "default_skill_profiles": [
    "intent_decision",
    "codebase_investigation",
    "implementation_with_verification"
  ]
}
```

主 Agent profile 必须显式支持长任务能力。否则系统会在没有 TaskGraph 时误以为只能短答，这是当前设计必须避免的核心退化。

#### CapabilityUnit

`CapabilityUnit` 是可组装能力的最小声明单元。

```json
{
  "capability_id": "rag.hybrid_local_knowledge",
  "authority": "orchestration.capability_unit",
  "supported_intent_actions": ["retrieve_knowledge", "continue"],
  "supported_execution_strategies": ["retrieval_augmented_answer", "specialist_handoff"],
  "requires_contracts": ["retrieval_contract", "source_citation_contract"],
  "return_schema_id": "capability.return.retrieval_answer",
  "skill_profile_id": "skill.rag_hybrid_retrieval"
}
```

能力单元只声明自己会什么、需要什么契约、如何回传，不负责决定当前 turn 是否该用它。
单 Agent 长任务示例：

```json
{
  "decision_id": "intent:decision:single-agent-long-task",
  "primary_action": "start_new",
  "secondary_actions": ["compound"],
  "reason": "用户要求完成一个复杂任务，但当前任务可以由主 Agent 通过多步规划、工具调用、自检和阶段提交完成，不需要多 Agent 图协调。",
  "requires_continuation": false,
  "task_complexity": "long_running",
  "execution_strategy": "single_agent_long_run",
  "runtime_lane": "single_agent_long",
  "requires_checkpoint": true,
  "requires_acceptance_gate": true,
  "confidence": 0.88,
  "ambiguities": []
}
```

对应 `IntentActionPlan` 不应直接列出所有工具步骤，而应生成单 Agent runtime assembly：

```json
{
  "plan_id": "intent:plan:single-agent-long-task",
  "decision_ref": "intent:decision:single-agent-long-task",
  "steps": [
    {
      "step_id": "intent:step:create-runtime-assembly",
      "action": "start_new",
      "module": "runtime_assembly_builder",
      "execution_strategy": "single_agent_long_run",
      "runtime_lane": "single_agent_long",
      "expected_output": "orchestration.runtime_assembly"
    },
    {
      "step_id": "intent:step:start-single-agent-run",
      "action": "execute",
      "module": "single_agent_runtime",
      "execution_strategy": "single_agent_long_run",
      "runtime_lane": "single_agent_long",
      "expected_output": "agent.run_handle"
    }
  ],
  "checkpoint_policy": "step_checkpoint",
  "acceptance_policy": "self_check_then_commit"
}
```

Graph coordination 示例只在需要多 Agent / 任务图协调时使用：

```json
{
  "decision_id": "intent:decision:graph-coordination-task",
  "primary_action": "start_new",
  "secondary_actions": ["delegate_work", "compound"],
  "reason": "用户要求多个角色并行协作并按阶段交接，需要任务图节点、边和 handoff 协调。",
  "requires_continuation": false,
  "task_complexity": "long_running",
  "execution_strategy": "graph_coordination_run",
  "runtime_lane": "graph_coordination",
  "requires_checkpoint": true,
  "requires_acceptance_gate": true,
  "confidence": 0.86,
  "ambiguities": []
}
```

对应 `IntentActionPlan` 生成图协调 runtime spec：

```json
{
  "plan_id": "intent:plan:graph-coordination-task",
  "decision_ref": "intent:decision:graph-coordination-task",
  "steps": [
    {
      "step_id": "intent:step:create-graph-runtime-spec",
      "action": "start_new",
      "module": "runtime_assembly_builder",
      "execution_strategy": "graph_coordination_run",
      "runtime_lane": "graph_coordination",
      "expected_output": "orchestration.runtime_assembly"
    },
    {
      "step_id": "intent:step:start-graph-run",
      "action": "execute",
      "module": "task_graph_scheduler",
      "execution_strategy": "graph_coordination_run",
      "runtime_lane": "graph_coordination",
      "expected_output": "task_graph.run_handle"
    }
  ],
  "checkpoint_policy": "event_checkpoint_spine",
  "acceptance_policy": "stage_acceptance_gate"
}
```

#### ContinuationCandidate

表示一个可被当前 turn 续接的候选证据。

```json
{
  "candidate_id": "cont:cand:...",
  "candidate_kind": "source_object | result_subset | task_result | bundle_item | memory_fact | workflow_state | workspace_object",
  "source_kind": "pdf | dataset | web | memory | task | code | workflow | workspace | browser | shell",
  "object_ref": "knowledge/E-commerce Data/employees.xlsx",
  "result_handle_id": "result:structured:employees:top5",
  "subset_handle_id": "subset:selection:employees:top5",
  "last_user_goal": "找出薪资最高的前五名员工，并带上姓名、部门、薪资。",
  "summary": "employees.xlsx 薪资最高的前五名员工结果。",
  "intent_signature": {
    "goal_segment": "employee_salary_analysis",
    "action_type": "structured_data_selection",
    "entity_types": ["employee", "department", "salary"],
    "allowed_followup_actions": ["group", "summarize", "compare", "filter_within_subset"]
  },
  "evidence_source": "task_summary_ref | tool_observation | session_recent_turn | memory_relevant_note",
  "recency_rank": 1,
  "confidence": 0.86,
  "constraints": {
    "scope": "result_subset",
    "must_not_expand_to_full_object": true
  }
}
```

#### ContinuationDecision

主 Agent 对当前 follow-up 的裁决结果。

```json
{
  "decision_id": "cont:decision:...",
  "selected_candidate_ids": ["cont:cand:employees-top5"],
  "decision": "continue | switch | clarify | reject",
  "reason": "用户说这些人和前五名，指向上一轮 employees.xlsx 的前五名员工结果。",
  "rewritten_query": "基于上一轮 employees.xlsx 薪资最高前五名员工结果，按部门归类总结，不读取全表。",
  "execution_target": {
    "source_kind": "dataset",
    "object_ref": "knowledge/E-commerce Data/employees.xlsx",
    "result_handle_id": "result:structured:employees:top5",
    "subset_handle_id": "subset:selection:employees:top5"
  },
  "ambiguities": [],
  "confidence": 0.91
}
```

#### ContinuationExecutionContract

传给工具或子 Agent 的工作包。

```json
{
  "authority": "continuation.execution_contract",
  "decision_ref": "cont:decision:...",
  "rewritten_query": "基于上一轮 employees.xlsx 薪资最高前五名员工结果，按部门归类总结，不读取全表。",
  "source_kind": "dataset",
  "object_ref": "knowledge/E-commerce Data/employees.xlsx",
  "result_handle_id": "result:structured:employees:top5",
  "subset_handle_id": "subset:selection:employees:top5",
  "scope_policy": "result_subset_only",
  "disallowed_actions": ["expand_to_full_object_without_user_request"],
  "return_contract": "continuation.return"
}
```

#### ContinuationReturn

子 Agent 或工具执行后回传的结构化结果。

```json
{
  "authority": "continuation.return",
  "consumed_candidate_ids": ["cont:cand:employees-top5"],
  "consumed_object_ref": "knowledge/E-commerce Data/employees.xlsx",
  "consumed_result_handle_id": "result:structured:employees:top5",
  "produced_result_handle_id": "result:structured:employees-top5-by-department",
  "produced_subset_handle_id": "",
  "can_continue": true,
  "continuation_summary": "已在前五名员工子集内按部门归类。",
  "blocked_reason": "",
  "binding_updates": []
}
```

### 6.2 层级职责

| 层级 | 职责 | 不再负责 |
|---|---|---|
| Memory | 用户偏好、项目长期事实、会话摘要、可回忆知识 | 当前 turn 执行绑定 |
| Intent Recognition Layer | 收集意图信号、生成意图假设、让 Agent 裁决当前 turn 动作 | 直接执行工具或替 Agent 选择最终对象 |
| Continuation Layer | 在 intent action 为 `continue` / `refine_scope` 时生成候选证据、改写 follow-up、构建续接 contract | 长期知识治理、顶层意图识别 |
| TaskUnderstanding | 提供任务类型、能力需求和结构化信号 | 从 state slot 中直接恢复对象、把 route 当成 intent |
| ContextResolver | 装配当前 turn 的显式输入、意图证据、候选证据和裁决结果 | 把 `active_*` 作为权威绑定 |
| TaskRunLoop | 执行 IntentActionPlan / contract，记录 return，更新候选轨迹 | 用工具观察直接覆盖当前 turn 裁决 |
| 子 Agent | 按 contract 执行并结构化回传 | 自己猜当前对象 |

### 6.3 能力域配置：ContinuationDomainProfile

Continuation Layer 必须配置化。核心框架只负责候选收集、裁决、改写、contract 构建和 return 解析；每个能力域通过 `ContinuationDomainProfile` 声明自己如何参与续接。

示例：

```json
{
  "profile_id": "continuation.domain.structured_data",
  "source_kind": "dataset",
  "candidate_kinds": ["source_object", "result_subset", "task_result"],
  "language_signals": ["these_items", "top_n", "group_by", "filter_within_result"],
  "intent_signature_fields": ["action_type", "entity_types", "metric_terms", "scope_terms"],
  "allowed_followup_actions": ["summarize", "group", "compare", "filter", "rank"],
  "disallowed_actions": ["expand_to_full_object_without_user_request"],
  "rewrite_policy": "make_dataset_followup_standalone",
  "default_scope_policy": "prefer_last_result_subset",
  "delegate_agent_profile_id": "structured_data_analysis_agent",
  "required_contract_fields": ["object_ref", "rewritten_query"],
  "optional_contract_fields": ["result_handle_id", "subset_handle_id", "scope_policy"],
  "return_schema_id": "continuation.return.structured_data",
  "ambiguity_policy": "clarify_when_cross_domain_conflict",
  "confidence_thresholds": {
    "auto_continue": 0.82,
    "clarify_below": 0.58
  }
}
```

PDF、结构化数据、RAG、代码阅读、任务图节点、浏览器页面、Shell 任务、写作章节、工作台对象都应该是 profile，而不是写死在 Continuation Layer 中。

首批建议 profile：

| profile_id | source_kind | 典型 follow-up | 委派目标 |
|---|---|---|---|
| `continuation.domain.pdf` | `pdf` | 这一页、这份报告、目录页、第四页 | `pdf_analysis_agent` |
| `continuation.domain.structured_data` | `dataset` | 这些人、前五名、按部门、不要回全表 | `structured_data_analysis_agent` |
| `continuation.domain.rag` | `knowledge` | 刚才那三类风险、继续用本地知识库 | `rag_analysis_agent` |
| `continuation.domain.task_bundle` | `task` | 第二个子任务、只展开第一个和第三个 | `main_interactive_agent` |
| `continuation.domain.workflow_graph` | `workflow` | 这个节点、上一阶段、失败分支 | `task_management_agent` |
| `continuation.domain.code_workspace` | `code` | 这个函数、刚才那个文件、这处修改 | `main_interactive_agent` 或代码专用 Agent |
| `continuation.domain.browser_session` | `browser` | 这个页面、上一步表单、刚才的按钮 | 浏览器能力 Agent |
| `continuation.domain.memory_fact` | `memory` | 你应该怎么称呼我、我的偏好是什么 | `memory_system_agent` |

配置原则：

1. profile 可以定义“如何生成候选”，但不能直接决定当前 turn 选谁。
2. profile 可以定义改写模板和委派目标，但最终仍由 ContinuationDecision 选择。
3. profile 可以声明返回 schema，子 Agent 必须按 schema 回传。
4. profile 的 `disallowed_actions` 必须进入 contract，不能只写在 prompt 里。
5. 新能力域先走 shadow 模式，确认候选和 decision trace 稳定后再 cutover。

### 6.4 通用 Profile Schema

为了避免 Continuation Layer 退化成 PDF / dataset 专用逻辑，profile 必须成为能力域接入续接系统的唯一配置入口。核心代码只认识 profile schema，不认识具体业务域名称。

最小 schema：

```json
{
  "profile_id": "continuation.domain.workflow_graph",
  "domain_label": "任务图",
  "source_kind": "workflow",
  "candidate_kinds": ["workflow_node", "workflow_stage", "workflow_branch", "task_result"],
  "candidate_sources": [
    "recent_turn_summary",
    "task_summary_ref",
    "tool_observation_projection",
    "runtime_trace_projection"
  ],
  "language_signals": ["this_node", "previous_stage", "failed_branch", "second_task"],
  "intent_signature_fields": ["action_type", "node_role", "stage_name", "ordinal_ref", "status_ref"],
  "allowed_followup_actions": ["inspect", "rerun", "summarize", "expand", "compare", "repair"],
  "disallowed_actions": ["mutate_graph_without_user_confirmation"],
  "rewrite_policy": "make_workflow_followup_standalone",
  "default_scope_policy": "prefer_last_referenced_runtime_object",
  "delegate_agent_profile_id": "task_management_agent",
  "required_contract_fields": ["object_ref", "rewritten_query", "scope_policy"],
  "optional_contract_fields": ["node_id", "stage_id", "branch_id", "result_handle_id"],
  "return_schema_id": "continuation.return.workflow_graph",
  "ambiguity_policy": "clarify_when_ordinal_or_node_reference_conflicts",
  "confidence_thresholds": {
    "auto_continue": 0.82,
    "clarify_below": 0.58
  }
}
```

配置字段分工：

| 字段 | 作用 | 核心层是否理解业务含义 |
|---|---|---|
| `source_kind` | 标识候选所属能力域 | 否，只用于匹配和隔离 |
| `candidate_kinds` | 声明本域能产生哪些候选 | 否，只做枚举校验 |
| `candidate_sources` | 声明候选可从哪些投影生成 | 是，只认识来源类型 |
| `language_signals` | 声明本域常见续接语言信号 | 否，由 profile 提供解释 |
| `intent_signature_fields` | 声明裁决时应关注的语义字段 | 否，只负责透传给裁决 prompt |
| `allowed_followup_actions` | 声明允许续接的动作 | 否，只做 contract 约束 |
| `disallowed_actions` | 声明禁止动作 | 是，必须进入执行 contract |
| `rewrite_policy` | 指定 follow-up 改写策略 | 是，按策略名称调用可插拔 rewriter |
| `delegate_agent_profile_id` | 指定默认委派目标 | 是，用于 contract 路由 |
| `return_schema_id` | 指定子 Agent 回传 schema | 是，用于解析和校验 |

硬性边界：

1. `candidate_collector` 不能出现 `if source_kind == "pdf"` 或 `if file_kind == "xlsx"` 这类业务分支。
2. 业务域差异只能存在于 profile、投影适配器和可插拔 rewriter 中。
3. 新增能力域时，优先新增 profile；只有缺少候选来源类型、contract 字段类型或 return schema 校验器时，才允许改核心层。
4. PDF 和结构化数据只是首批 profile，不是架构中心。
5. 至少使用一个非文件域 profile 作为 Phase 1 验收用例，防止实现偏向数据文件。

---

## 7. 固定执行流

### 7.1 当前 turn 进入前

```text
load session recent turns
load task summary refs
load latest tool observation projections
load lightweight memory hints when semantic recall may be relevant
collect intent signals
build intent hypotheses
build continuation candidates only when hypotheses include continue/refine_scope/switch_target
```

意图信号和候选生成只负责收集证据，不做最终裁决。

### 7.2 主 Agent 顶层意图裁决

主 Agent 收到：

```text
用户原句
IntentFrame
IntentHypotheses
候选证据摘要
候选之间的差异
允许动作
需要避免的歧义
```

主 Agent 先输出 `IntentDecision`。

裁决规则：

1. 当前用户显式给出新对象或新问题时，优先判断 `start_new` 或 `switch_target`，不要强行续接。
2. 当前用户使用“这些 / 刚才 / 前五名 / 第二个节点 / 这个页面”等指代语时，判断是否 `continue` 或 `refine_scope`。
3. 当前用户要求“记得 / 偏好 / 以后默认 / 你叫我什么”时，进入 `recall_memory`，不要走 RAG 或文件续接。
4. 当前用户要求“查资料 / 本地知识库 / 网上 / 官方文档 / 最新”时，进入 `retrieve_knowledge`，再由检索层决定 RAG / web / official。
5. 当前用户要求“让某个 agent 做 / 子任务 / 专家分析”时，进入 `delegate_work`，再判断是否需要 continuation contract。
6. 候选冲突且置信度不足时，进入 `clarify`。
7. 证据不足或请求越界时，进入 `reject_or_boundary`，不要为了执行而猜。

同时必须输出执行力相关字段：

```text
task_complexity = single_step | multi_step | long_running
execution_strategy = direct_answer | single_react_loop | single_agent_long_run | single_agent_background_run | retrieval_augmented_answer | specialist_handoff | specialist_subagent_long_run | graph_coordination_run | human_gate
runtime_lane = interactive | single_agent_long | background | graph_coordination
requires_checkpoint = true | false
requires_acceptance_gate = true | false
```

判断规则：

1. 单步、低风险、上下文明确：`interactive + direct_answer/single_react_loop`。
2. 单步但需要专门能力：`interactive + specialist_handoff`。
3. 主 Agent 可独立完成但需要多步、阶段提交或长时间工具执行：`single_agent_long + single_agent_long_run`。
4. 主 Agent 或单个专门 Agent 可后台处理、不要求立即完整答案：`background + single_agent_background_run/specialist_subagent_long_run`。
5. 需要多 Agent、图节点/边、并行调度或跨角色 handoff：`graph_coordination + graph_coordination_run`。
6. 涉及破坏性操作、权限、重大范围变化：`human_gate`。

### 7.3 编排系统组装 RuntimeAssembly

主 Agent 输出 `IntentDecision` 后，必须由现有编排系统把裁决转为可执行的 `RuntimeAssembly` / runtime spec，而不是让 TaskRunLoop、ContextResolver、工具路由各自临时解释。

编排系统输入：

```text
IntentDecision
IntentActionPlan draft
available AgentRuntimeProfile[]
available RuntimeLaneProfile[]
available CapabilityUnit[]
available SkillProfile[]
task context / risk / permission surface
optional ContinuationDecision ref
```

编排系统输出：

```text
RuntimeAssembly / runtime_spec
resolved runtime_lane
resolved agent_profile
resolved capability_units
resolved skill_profiles
contract package
checkpoint policy
acceptance policy
progress policy
```

组装规则：

1. `direct_answer` / `single_react_loop` 默认组装主 Agent interactive assembly。
2. `single_agent_long_run` 必须组装主 Agent 或指定单 Agent 的长任务 assembly，带 step checkpoint 和 committed output contract。
3. `single_agent_background_run` 必须组装后台单 Agent assembly，带 progress contract 和 lifecycle checkpoint。
4. `specialist_handoff` 必须组装 bounded 子 Agent handoff assembly，带 return schema。
5. `specialist_subagent_long_run` 必须组装专业子 Agent 长任务 assembly，带 run handle 和 progress event。
6. `retrieval_augmented_answer` 必须组装检索 contract，而不是降级成普通 `search_text`。
7. `graph_coordination_run` 必须组装 TaskGraph coordination runtime spec，只有这一路允许进入 TaskGraph scheduler。
8. 没有任务图定义时，不能把 `single_agent_long_run` 降级成单轮回答；应该启动 Single Agent Runtime。

### 7.4 Continuation 裁决

只有 `IntentDecision.requires_continuation=true` 时，主 Agent 才继续输出 `ContinuationDecision`。

续接裁决规则：

1. 当前用户显式给出路径时，视为 `switch`。
2. 用户使用“这些人 / 前五名 / 刚才那几个”时，优先匹配 result_subset 或 task_result。
3. 用户使用“这份 PDF / 第三页 / 目录页”时，优先匹配 pdf 候选。
4. 用户请求“回到 inventory.xlsx / 换成 employees.xlsx”时，进入 `switch`，不是 follow-up。
5. 候选冲突且置信度不足时，进入 `clarify`。

### 7.5 Query Rewriting

所有 `continue` / `refine_scope` / `switch_target + follow-up action` 执行前必须生成 `rewritten_query`。

要求：

1. 可独立执行。
2. 包含对象和范围。
3. 包含不得越界的约束。
4. 不暴露内部句柄给用户，但可传给工具和子 Agent。

### 7.6 子 Agent 委派

主 Agent 发给子 Agent 的指令应像真实工作委派，而不是系统字段说明。

推荐形态：

```text
你是一名结构化数据分析员。

你现在继续处理上一轮 employees.xlsx 的薪资前五名员工结果。
这次任务只允许基于该五人子集按部门归类总结，不允许重新统计全表。

你需要返回：
1. 面向用户的简洁结论。
2. 你实际使用的对象和结果范围。
3. 是否还能继续基于这个结果追问。
4. 如果无法执行，说明缺少什么证据，不要补猜。
```

同时随附机器可读 contract。

### 7.7 回传与收口

子 Agent 必须回传 `ContinuationReturn`。主 Agent 收口时只使用：

```text
final_answer
continuation_return.continuation_summary
produced_result_handle_id
can_continue
blocked_reason
```

主 Agent 不再从原始工具中间输出里猜后续对象。

---

## 8. 数据模型设计

### 8.1 新增模块建议

```text
backend/intent/
  __init__.py
  models.py
  signal_collector.py
  hypothesis_builder.py
  decision_prompt.py
  decision_parser.py
  action_planner.py
  trace_adapter.py
backend/continuation/
  __init__.py
  models.py
  candidate_collector.py
  decision_prompt.py
  decision_parser.py
  query_rewriter.py
  execution_contract.py
  return_parser.py
  trace_adapter.py
```

### 8.2 模型字段

核心 dataclass：

```text
IntentFrame
IntentSignal
IntentHypothesis
IntentDecision
IntentActionStep
IntentActionPlan
IntentTrace
RuntimeAssembly
RuntimeLaneProfile
AgentRuntimeProfile
CapabilityUnit
OrchestrationProfile
ContinuationCandidate
ContinuationIntentSignature
ContinuationDecision
ContinuationExecutionTarget
ContinuationExecutionContract
ContinuationReturn
ContinuationTrace
```

Intent 与 Continuation 的关系：

```text
IntentFrame
  -> IntentHypothesis[]
  -> IntentDecision
  -> OrchestrationSystem runtime assembly
  -> RuntimeAssembly / IntentActionPlan
      -> if requires_continuation:
            ContinuationCandidate[]
            ContinuationDecision
            ContinuationExecutionContract
            ContinuationReturn
```

`IntentDecision` 是顶层裁决，`RuntimeAssembly / IntentActionPlan` 是现有编排系统的结构化运行装配结果，`ContinuationDecision` 是续接子裁决。任何 runtime 路由都不能跳过 `IntentDecision` / runtime assembly 直接消费旧 active binding。

### 8.3 Intent 信号来源

| 来源 | 说明 | 例子 |
|---|---|---|
| 用户原句显式动作 | 用户直接表达要做什么 | “换成 employees.xlsx”“查最新”“记住” |
| 指代词和省略 | 需要结合上下文判断 | “这些人”“刚才那个”“第二个” |
| 范围约束 | 限定执行边界 | “只看前五名”“不要扩展回全表” |
| 记忆召回标记 | 指向长期或会话记忆 | “你记得我怎么称呼吗” |
| 检索标记 | 指向本地 RAG、web、官方来源或时效信息 | “知识库里”“网上查”“官方文档”“最新” |
| 委派标记 | 指向子 Agent 或工具协作 | “让数据分析 agent 做” |
| 任务图标记 | 指向节点、阶段、分支、子任务 | “这个节点”“上一阶段”“第二个子任务” |
| 能力边界标记 | 需要澄清或拒绝 | “随便猜”“没有资料也给结论” |

### 8.4 Continuation 候选来源

| 来源 | 说明 | 优先级 |
|---|---|---:|
| 当前 turn 显式路径 | 用户直接说出 `.pdf` / `.xlsx` | 最高 |
| 最近 task_summary_refs | 子 Agent 或工具产出的结构化摘要 | 高 |
| 最近 continuation_return | 上一次续接回传 | 高 |
| 最近 tool_observation_projection | 工具产生的对象和结果 | 中 |
| session recent turns | 最近对话自然语言摘要 | 中 |
| relevant memory notes | 偏好和稳定事实 | 低，不作为执行对象 |

### 8.5 候选排序

排序不只看时间，还要看意图兼容性：

```text
score = recency_score
      + intent_compatibility_score
      + lexical_anchor_score
      + result_specificity_score
      - domain_conflict_penalty
```

其中 domain conflict 示例：

```text
当前请求含“这些人 / 前五名 / 部门”
PDF candidate penalty = high
dataset subset candidate bonus = high
```

### 8.6 配置存储

建议新增配置注册器：

```text
backend/intent/profile_registry.py
backend/continuation/profile_registry.py
storage/orchestration/intent_domain_profiles.json
storage/orchestration/intent_orchestration_profiles.json
storage/orchestration/runtime_lane_profiles.json
storage/orchestration/agent_runtime_profiles.json
storage/orchestration/capability_units.json
storage/orchestration/continuation_domain_profiles.json
```

默认 profile 由代码内置，用户配置只覆盖可编辑字段。系统内置 profile 需要和 `AgentRuntimeProfile`、capability unit、skill runtime view 建立引用关系，但不能反向依赖某个具体工具实现。

配置加载顺序：

```text
built-in defaults
  -> storage/orchestration/intent_domain_profiles.json
  -> storage/orchestration/intent_orchestration_profiles.json
  -> storage/orchestration/runtime_lane_profiles.json
  -> storage/orchestration/agent_runtime_profiles.json
  -> storage/orchestration/capability_units.json
  -> storage/orchestration/continuation_domain_profiles.json
  -> task-specific override
  -> current turn explicit constraints
```

优先级越高，作用范围越窄。当前 turn 显式约束可以覆盖 profile，但不能绕过 profile 声明的安全边界。

### 8.7 编排能力配置

Intent profile 需要能声明“这个意图可以配置哪些编排能力”，而不是只声明关键词。

建议新增：

```text
storage/orchestration/intent_orchestration_profiles.json
```

配置结构：

```json
{
  "profile_id": "intent.orchestration.long_task_default",
  "authority": "orchestration.intent_orchestration_profile",
  "intent_actions": ["start_new", "compound", "delegate_work"],
  "complexity_classifier": {
    "long_running_when": {
      "min_expected_steps": 3,
      "requires_artifacts": true,
      "requires_acceptance": true,
      "estimated_runtime_seconds_gte": 120
    },
    "graph_coordination_when": {
      "min_distinct_agent_roles": 2,
      "requires_explicit_stage_graph": true,
      "requires_parallel_nodes": true,
      "requires_cross_agent_handoff": true
    }
  },
  "execution_strategy_policy": {
    "single_step": ["direct_answer", "single_react_loop", "specialist_handoff"],
    "multi_step": ["single_agent_long_run", "specialist_handoff", "specialist_subagent_long_run"],
    "long_running": ["single_agent_long_run", "single_agent_background_run", "specialist_subagent_long_run"],
    "graph_coordination": ["graph_coordination_run"]
  },
  "runtime_lane_policy": {
    "direct_answer": "interactive",
    "single_react_loop": "interactive",
    "single_agent_long_run": "single_agent_long",
    "single_agent_background_run": "background",
    "specialist_handoff": "interactive",
    "specialist_subagent_long_run": "background",
    "graph_coordination_run": "graph_coordination"
  },
  "required_contracts_by_strategy": {
    "single_agent_long_run": ["input_contract", "output_contract", "acceptance_contract"],
    "single_agent_background_run": ["input_contract", "progress_contract", "output_contract", "acceptance_contract"],
    "specialist_handoff": ["handoff_contract", "return_contract"],
    "specialist_subagent_long_run": ["handoff_contract", "progress_contract", "return_contract"],
    "graph_coordination_run": ["input_contract", "output_contract", "handoff_contract", "acceptance_contract"]
  },
  "checkpoint_policy_by_strategy": {
    "direct_answer": "none",
    "single_react_loop": "event_trace_only",
    "single_agent_long_run": "step_checkpoint",
    "single_agent_background_run": "agent_lifecycle_checkpoint",
    "specialist_handoff": "handoff_checkpoint",
    "specialist_subagent_long_run": "agent_lifecycle_checkpoint",
    "graph_coordination_run": "event_checkpoint_spine"
  }
}
```

配置边界：

1. Intent profile 只能声明可选执行策略和约束，不能直接指定最终策略。
2. RuntimeLane profile 决定同步/异步、checkpoint、resume、权限和工具预算。
3. AgentRuntimeProfile 决定主 Agent 或子 Agent 是否支持单 Agent 长任务、后台运行、可恢复运行和工具预算。
4. TaskGraph profile 只决定图协调任务如何编译成节点、边、阶段和验收门。
5. Capability unit 决定某个能力是否支持 handoff、streaming、checkpoint 和 return schema。
6. Graph coordination 不能成为 long_running 的默认策略，除非命中多 Agent / 图式协调条件。

---

## 9. 与现有模块的迁移关系

### 9.1 ContextResolver

改造目标：

1. `ContextResolver` 不再直接把 `state_snapshot.context_slots.active_*` 转成权威 `ResolvedBinding`。
2. 它负责装配 `IntentFrame` 所需的显式输入、recent projections、task summary refs 和 memory hints。
3. 它只接收 `intent_decision`、`intent_action_plan`、`continuation_candidates` 和可选 `continuation_decision` 作为当前 turn 裁决结果。
4. `ResolvedBinding` 保留，但来源从 `session_state` 改为：

```text
explicit_user_input
intent_decision
continuation_decision
task_summary
```

5. `restore_candidates_used` 只做诊断，不参与裁决。

### 9.2 TaskUnderstanding

改造目标：

1. `_collect_task_signals()` 不再从 `active_bindings` 推出 `bound_dataset_path / bound_pdf_path`。
2. `_resolve_followup_target()` 只识别语言形态，不决定对象。
3. `TaskUnderstanding` 输出语言信号和能力信号，供 Intent Layer 使用：

```text
explicit_switch
object_followup
result_subset_followup
bundle_ordinal_followup
memory_recall
general
```

4. 对象选择交给 `ContinuationDecision`，顶层动作选择交给 `IntentDecision`。
5. `intent` 字段不再混用执行路径；执行路径进入 `route_hint` / `capability_resolution`，用户动作进入 `IntentDecision.primary_action`。

### 9.3 TaskRunLoop

改造目标：

1. 执行前读取 `IntentActionPlan`，不得绕过 IntentDecision 直接消费旧 `active_*`。
2. 工具观察仍可生成候选证据，但不直接覆盖当前 turn 绑定。
3. 当 action plan 包含 continuation step 时，子 Agent 输入必须包含 `ContinuationExecutionContract`。
4. 子 Agent 输入必须包含面向角色的 intent 摘要，不能只塞系统字段。
5. 子 Agent 输出必须被解析为结构化 return。
6. 当 `execution_strategy=single_agent_long_run` 时，TaskRunLoop 运行主 Agent 长任务循环，写入 step checkpoint 和 committed output。
7. 当 `execution_strategy=single_agent_background_run` 或 `specialist_subagent_long_run` 时，TaskRunLoop 必须走后台 Agent lifecycle，不阻塞主 turn。
8. 当 `execution_strategy=graph_coordination_run` 时，TaskRunLoop 只负责创建/恢复 Graph Coordination Run，并把执行交给 TaskGraph Scheduler。
9. 当 `execution_strategy=single_react_loop` 时，保留 Agent 的观察-行动循环，不把 IntentActionPlan 当成固定脚本。
10. 运行 trace 写入：

```text
intent_frame_built
intent_hypotheses_built
intent_decision_made
intent_action_plan_built
continuation_candidates_built
continuation_decision_made
continuation_contract_built
continuation_return_received
```

### 9.3.1 Single Agent Runtime

改造目标：

1. 接收 `single_agent_long_run` / `single_agent_background_run` runtime assembly。
2. 支持主 Agent 多步计划、工具观察、阶段提交、自检、修正和恢复。
3. 为单 Agent 长任务生成 run handle、step checkpoint、progress event、committed output ref。
4. 不要求存在任务图，也不能因为没有任务图就降级为单轮回答。
5. checkpoint / resume / interrupt 由 Single Agent Runtime 和 RuntimeLane 负责，不能依赖对话上下文记忆进度。

### 9.3.2 Graph Coordination / Scheduler

改造目标：

1. 只接收 `IntentActionPlan` 中的 `graph_coordination_run` step。
2. 编译或恢复多 Agent / 任务图协调运行。
3. 复用既有 `TaskGraphRuntimeSpec`、`ContractManifest`、handoff contract、checkpoint adapter。
4. Intent Layer 只传入目标、边界、复杂度和策略，不直接生成节点内部 prompt。
5. 节点内部执行仍由 AgentRuntimeProfile、RuntimeLaneProfile、CapabilityUnit 和节点契约决定。
6. checkpoint / resume / interrupt 必须由 Scheduler 和 RuntimeLane 负责，不能依赖对话上下文记忆进度。

### 9.4 MemoryRuntimeView

改造目标：

1. `restore_candidates` 保留为候选来源之一。
2. `state_snapshot` 不再直接进入当前 turn 绑定。
3. 长期记忆召回结果只作为 `memory_fact` 候选，不能成为 `source_object`。

### 9.5 Skills / Agent Prompt

Skills 需要补充：

1. 主 Agent 如何先判断当前 turn 的用户动作，而不是直接猜对象。
2. 主 Agent 如何区分新任务、续接、切换、约束收紧、记忆召回、检索、委派、澄清和拒绝。
3. 主 Agent 如何基于候选证据做续接判断。
4. 何时必须改写 follow-up。
5. 何时委派子 Agent。
6. 何时使用主 Agent 自主长任务、后台单 Agent、专门子 Agent 长任务或 Graph coordination，而不是把“长任务”一律等同任务图。
7. 子 Agent 如何按 intent 摘要和 contract 执行并回传。
8. 遇到证据不足时如何承认边界。

### 9.6 Intent / Capability / Profile Registry

改造目标：

1. Intent Layer 不直接识别所有业务域，而是通过 intent profile 注册动作信号。
2. Continuation Layer 不直接识别所有业务域，而是通过 continuation profile 注册候选和 contract。
3. `profile_registry` 按 `source_kind`、`task_kind`、`capability_request`、`agent_profile_id` 匹配 profile。
4. capability unit 可以声明自己支持哪些 intent action、是否支持 continuation，以及支持哪些 candidate / return schema。
5. Skill prompt 只负责教 Agent 如何使用该能力，不承担 profile 配置职责。

---

## 10. 分阶段实施计划

### Phase 1：Intent 建模和影子链路

目标：新增 Intent 模型、信号收集、意图假设和 trace，不改变现有执行结果。

文件：

```text
backend/intent/models.py
backend/intent/signal_collector.py
backend/intent/hypothesis_builder.py
backend/intent/profile_registry.py
backend/intent/trace_adapter.py
storage/orchestration/intent_domain_profiles.json
backend/tests/intent_signal_regression.py
backend/tests/intent_hypothesis_regression.py
```

完成标准：

1. 能从用户原句、task_summary_refs、tool_observation_projection、recent turns 和 memory hints 生成 IntentFrame。
2. 能识别 `start_new / continue / switch_target / refine_scope / recall_memory / retrieve_knowledge / delegate_work / clarify / compound` 的候选假设。
3. `turn 57` 的顶层假设必须是 `refine_scope + continue + delegate_work`，而不是单纯 dataset route。
4. 记忆召回 turn 25 / 52 必须生成 `recall_memory` hypothesis，不能被 RAG 或文件续接吞掉。
5. 长任务请求必须生成 `task_complexity` 和候选 `execution_strategy`，但不改变实际执行。
6. Intent trace 可在长跑 artifact 中查看。

### Phase 2：编排系统运行装配影子链路

目标：基于现有 runtime assembly 结构补充 intent 驱动的编排 profile 和影子装配链路，只生成影子 `RuntimeAssembly` / runtime spec，不改变实际执行。

文件：

```text
backend/orchestration/runtime_loop/runtime_assembly_builder.py
backend/orchestration/runtime_loop/runtime_assembly_models.py
backend/orchestration/agent_runtime_registry.py
storage/orchestration/intent_orchestration_profiles.json
storage/orchestration/runtime_lane_profiles.json
storage/orchestration/agent_runtime_profiles.json
storage/orchestration/capability_units.json
backend/tests/orchestration_runtime_assembly_regression.py
backend/tests/intent_execution_strategy_regression.py
backend/tests/intent_long_task_escalation_regression.py
```

完成标准：

1. 同一个 IntentHypothesis 可以组装为不同 `RuntimeAssembly` 候选，但不直接执行。
2. 普通多步任务默认候选包含 `single_agent_long_run`，不能默认变成 `graph_coordination_run`。
3. 明确多 Agent、节点/边、阶段、并发或 handoff 时，才生成 `graph_coordination_run` runtime spec。
4. `retrieval_augmented_answer` runtime assembly 必须指向 RAG / hybrid retrieval capability，不允许退化成普通 `search_text`。
5. runtime assembly trace 可与旧 route / tool plan 做 diff。

### Phase 3：主 Agent Intent 裁决与编排决策接入

目标：让主 Agent 根据 IntentFrame / IntentHypotheses 输出 `IntentDecision`，再由现有编排系统生成权威 `RuntimeAssembly` / runtime spec，但先以 shadow/guarded primary 方式运行。

文件：

```text
backend/intent/decision_prompt.py
backend/intent/decision_parser.py
backend/intent/action_planner.py
backend/orchestration/agent_runtime_chain.py
backend/orchestration/runtime_loop/runtime_assembly_builder.py
storage/orchestration/intent_domain_profiles.json
storage/orchestration/intent_orchestration_profiles.json
backend/tests/intent_decision_regression.py
backend/tests/orchestration_runtime_assembly_regression.py
```

完成标准：

1. “你记得我怎么称呼吗”产生 `recall_memory`，不进入 continuation。
2. “用本地知识库查一下”产生 `retrieve_knowledge`，并组装 RAG runtime assembly。
3. “帮我追踪问题并修复”产生 `single_agent_long_run`，不要求存在任务图。
4. “后台继续分析并告诉我进度”产生 `single_agent_background_run`，不阻塞主 turn。
5. “让规划、执行、审核三个 Agent 按阶段协作”才产生 `graph_coordination_run`。
6. 编排系统能根据同一个 IntentDecision 组装不同 RuntimeAssembly，而不是把执行策略写死在 intent parser 中。

### Phase 4：Continuation 候选、裁决和改写接入

目标：只有 IntentDecision 需要续接时，才进入 Continuation 候选、裁决、改写和执行契约。

文件：

```text
backend/continuation/models.py
backend/continuation/candidate_collector.py
backend/continuation/profile_registry.py
backend/continuation/decision_prompt.py
backend/continuation/decision_parser.py
backend/continuation/query_rewriter.py
backend/continuation/execution_contract.py
backend/continuation/trace_adapter.py
storage/orchestration/continuation_domain_profiles.json
backend/tests/continuation_candidate_regression.py
backend/tests/continuation_decision_regression.py
```

完成标准：

1. “这些人 / 前五名 / 按部门”先被裁决为 `refine_scope + continue`，再选择 employees subset。
2. “第三页 / 这份 PDF”先被裁决为 `continue`，再选择 PDF。
3. 显式切换 `.xlsx` 或 `.pdf` 时产生 `switch_target`，不是旧对象 follow-up。
4. `turn 57` 能生成 dataset subset 候选和 PDF 候选，并给 PDF 标记 domain conflict。
5. PDF / dataset 候选逻辑来自 profile，而不是写死在 collector 中。
6. 冲突候选产生 `clarify`，不擅自执行。

### Phase 5：Runtime 分流接入

目标：TaskRunLoop 执行 `RuntimeAssembly` / runtime spec，并按 execution_strategy 分流到 interactive、single agent long、background、specialist handoff 或 graph coordination。

文件：

```text
backend/orchestration/runtime_loop/task_run_loop.py
backend/orchestration/runtime_loop/runtime_assembly_builder.py
backend/orchestration/runtime_loop/runtime_assembly_models.py
backend/orchestration/runtime_loop/task_graph_scheduler.py
backend/orchestration/runtime_loop/langgraph_checkpoint_adapter.py
backend/orchestration/agent_runtime_chain.py
backend/tests/single_agent_runtime_regression.py
backend/tests/orchestration_runtime_dispatch_regression.py
```

完成标准：

1. `single_agent_long_run` 进入主 Agent 长任务循环，写入 step checkpoint、progress event 和 committed output ref。
2. `single_agent_background_run` / `specialist_subagent_long_run` 进入后台 Agent lifecycle，不阻塞主 turn。
3. `graph_coordination_run` 只创建/恢复 Graph Coordination Run，并把执行交给 TaskGraph Scheduler。
4. 没有任务图时，主 Agent 长任务不能降级为单轮回答。
5. `single_react_loop` 继续保留观察-行动循环，不被 IntentActionPlan 固化成脚本。

### Phase 6：ContextResolver 和 TaskUnderstanding 降权

目标：停止旧 state slot 直接绑定，并让 TaskUnderstanding 退回信号提供层。

文件：

```text
backend/context_management/resolver.py
backend/context_management/current_turn.py
backend/understanding/task_understanding.py
backend/tests/agent_main_assembly_semantic_boundary_regression.py
```

完成标准：

1. `ContextResolver` 只接受 explicit input、IntentDecision、RuntimeAssembly 或 ContinuationDecision 作为权威裁决来源。
2. `restore_candidates_used` 仅用于诊断。
3. 旧测试中依赖 `active_dataset` 的断言迁移到 intent decision / continuation candidate / decision。
4. `turn 57` 不再把 PDF binding 放入 structured data task。
5. route hint 不能绕过 IntentDecision / runtime assembly 直接决定当前对象。

### Phase 7：子 Agent contract 和 return

目标：让委派链路有明确的输入和回传。

文件：

```text
backend/intent/action_planner.py
backend/continuation/execution_contract.py
backend/continuation/return_parser.py
backend/orchestration/runtime_loop/task_run_loop.py
backend/evidence/structured_data_worker.py
backend/evidence/pdf_worker.py
backend/tests/continuation_subagent_contract_regression.py
```

完成标准：

1. PDF 子 Agent 收到 PDF intent 摘要和 PDF contract。
2. Structured Data 子 Agent 收到 dataset / subset intent 摘要和 contract。
3. 子 Agent 回传 consumed / produced handle。
4. 主 Agent 只根据 return 收口，不再猜工具中间输出。

### Phase 8：Memory 边界收紧

目标：长期记忆和 session memory 不再承担执行对象续接。

文件：

```text
backend/memory_system/runtime_view.py
backend/memory_system/bundle_service.py
backend/context_policy/package_builder.py
backend/tests/state_memory_context_policy_regression.py
backend/tests/memory_runtime_route_regression.py
```

完成标准：

1. `memory_fact` 可以帮助称呼、偏好、长期约定召回。
2. `memory_fact` 不产生 `source_object` 绑定。
3. 称呼偏好 turn 25 / 52 能召回，且不污染 PDF / dataset 续接。

### Phase 8.5：通用 profile 扩展验证

目标：验证 Intent Layer、编排 profile 和 Continuation Layer 都不是 PDF / dataset 专用能力。

文件：

```text
backend/intent/profile_registry.py
backend/continuation/profile_registry.py
backend/orchestration/capability_registry.py
storage/orchestration/intent_domain_profiles.json
storage/orchestration/intent_orchestration_profiles.json
storage/orchestration/capability_units.json
storage/orchestration/continuation_domain_profiles.json
backend/tests/intent_profile_registry_regression.py
backend/tests/continuation_profile_registry_regression.py
backend/tests/continuation_non_file_domain_regression.py
```

完成标准：

1. 至少新增一个非文件类 intent / continuation profile，例如 `task_bundle` 或 `workflow_graph`。
2. 非文件 profile 能生成 intent hypothesis、参与 decision、生成 contract。
3. 文件类 profile 与非文件类 profile 共用同一套模型和 trace。
4. 旧的 PDF / dataset 规则不能出现在通用 collector 的硬编码分支中。
5. workflow_graph profile 只能在命中图式协调条件时推荐 `graph_coordination_run`；普通多步请求应推荐 `single_agent_long_run` 或 `single_agent_background_run`。

### Phase 9：长跑验证和旧路径清理

目标：删除无用旧路径，确保六十轮长跑稳定。

文件：

```text
backend/tests/system_eval/long_runner.py
backend/tests/system_eval/long_scenarios.py
backend/context_management/resolver.py
backend/understanding/task_understanding.py
backend/orchestration/runtime_loop/task_run_loop.py
```

完成标准：

1. `rerun-60turn` 至少通过当前 8 个失败点。
2. artifact 中能看到 intent frame / hypothesis / decision / runtime assembly / continuation candidate / decision / contract / return。
3. 旧的 `active_*` 权威绑定路径被删除或降级为候选来源。
4. 不保留无用兼容分支。

---

## 11. 验证矩阵

| 场景 | 应验证 |
|---|---|
| 新任务识别 | “帮我写一个新计划”产生 `start_new`，不续接旧 PDF / dataset |
| PDF follow-up | “第三页 / 这份 PDF / 目录页”选择 PDF candidate |
| Dataset follow-up | “这些人 / 前五名 / 按部门”选择 result_subset candidate |
| 范围收紧 | “只总结这前五名，不要扩展回全表”产生 `refine_scope` contract |
| 显式切换 | “换成 employees.xlsx”产生 `switch_target`，覆盖旧候选 |
| RAG 检索 | “用本地知识库查一下”产生 `retrieve_knowledge`，不被 search_text 误当普通文本搜索 |
| 多会话隔离 | doc / ops / live session 不互相污染 |
| Bundle follow-up | “只展开第二个子任务”产生 task_bundle intent 并选择 bundle item |
| 主 Agent 长任务 | “帮我追踪问题并修复”可产生 `single_agent_long_run`，不要求任务图 |
| 后台单 Agent 长任务 | “后台继续分析并告诉我进度”产生 `single_agent_background_run` |
| Graph coordination | “让规划、执行、审核三个 Agent 按阶段协作”才产生 `graph_coordination_run` |
| 短任务 fast path | “这个词是什么意思”不触发复杂裁决和任务图 |
| ReAct 执行循环 | 单步工具任务保留观察-行动循环，不被 action plan 固化 |
| Checkpoint / resume | 长任务中断后通过 checkpoint 恢复，不依赖 active_* |
| 长期偏好 recall | “你之后应该怎么称呼我”产生 `recall_memory` 并命中 durable memory |
| 证据不足 | 不猜对象，输出 clarify 或不足边界 |
| 子 Agent 委派 | contract 与 return 一致 |

---

## 12. 风险和控制

### 12.1 风险：Agent 裁决不稳定

控制：

1. Intent hypotheses 限制在 Top 5，Continuation candidates 限制在 Top 5。
2. IntentFrame、候选摘要使用固定 schema。
3. intent decision parser 和 continuation decision parser 都必须 fail-closed。
4. 低置信度进入 clarify。

### 12.1.1 风险：Intent Layer 退化成规则路由器

控制：

1. profile 和规则只能生成 hypothesis，不能直接生成最终 action。
2. `IntentDecision.reason` 必须解释用户语义，不允许只写“命中规则”。
3. route hint 不能作为 `primary_action`，`rag/pdf/structured_data` 只能是执行路径。
4. 测试必须覆盖同 route 不同 intent，例如 `retrieve_knowledge` 与 `continue` 都可能走 RAG，但语义不同。
5. 对复杂 turn 使用 Agent 裁决，对显式简单 turn 才允许 deterministic decision。

### 12.1.2 风险：编排组装退化成硬编码路由

控制：

1. 编排组装只能消费 `IntentDecision`、profile、capability unit 和 runtime context，不能重新读取旧 `active_*` 做目标判断。
2. 编排组装只能生成 `RuntimeAssembly` / runtime spec，不能生成工具逐步脚本。
3. execution_strategy 的选择必须可解释，trace 中要记录被排除的模式和原因。
4. `graph_coordination_run` 必须有多 Agent / 图式协调证据，不能因为 `long_running` 自动命中。
5. 新 capability 只能通过 profile / registry 接入，不能在编排组装里新增业务 if/else。

### 12.2 风险：引入额外模型调用导致慢

控制：

1. 只在意图信号复杂、follow-up 语言信号存在或多候选冲突时调用裁决。
2. 显式路径切换直接决策。
3. 单一高置信候选可走 deterministic decision。
4. 裁决 prompt 使用小上下文，只传 IntentFrame 和候选摘要。

### 12.2.1 风险：意图层破坏 Agent 执行力

控制：

1. IntentActionPlan 只约束目标、策略、边界和 contract，不生成工具逐步脚本。
2. `single_react_loop` 必须允许 Agent 根据观察结果调整下一步。
3. `single_agent_long_run` 必须允许主 Agent 自主规划、观察、行动和修正。
4. `graph_coordination_run` 必须交给 Scheduler 和 checkpoint 机制，Intent Layer 不直接执行图节点。
5. 短任务 fast path 要有测试，避免所有请求都被升级成重编排。
6. 长任务必须有 run handle、checkpoint、handoff packet 或 committed output ref，避免“看似启动，实际靠上下文硬记”。
7. 后台管理任务必须异步，不能阻塞主 turn。

### 12.2.2 风险：长任务被误压成单轮回答

控制：

1. Intent profile 必须声明长任务复杂度信号，例如多阶段、产物、验收、恢复、并发、子 Agent 协作。
2. 当 `task_complexity=long_running` 时，默认候选策略必须优先包含 `single_agent_long_run` 或 `single_agent_background_run`。
3. 只有命中多 Agent / 显式图式协调条件时，才允许选择 `graph_coordination_run`。
4. 如果缺少必要 contract，应先生成计划或澄清，而不是降级为普通回答。
5. 长任务执行状态必须能在 agent run monitor / progress event / artifact 中查看；Graph coordination 还应能在 TaskGraph monitor 中查看。

### 12.3 风险：旧 active_* 路径残留

控制：

1. Phase 6 后禁止 `ContextResolver` 直接把 `state_snapshot.context_slots.active_*` 变成权威 binding。
2. 旧字段只允许出现在 `candidate.metadata` 或 trace diagnostics。
3. 回归测试扫描 `source=session_state` 的权威 binding。

### 12.4 风险：Prompt 写成开发说明

控制：

所有 Agent 指令必须写成角色和任务语言，例如：

```text
你是一名结构化数据分析员。
你只负责基于给定数据结果继续分析。
你不能扩大到全表，除非用户明确要求。
```

不能写成：

```text
这是 continuation 节点。
根据 contract 执行 structured_data_followup。
```

---

## 13. 文件级执行清单

### 新增

```text
backend/intent/__init__.py
backend/intent/models.py
backend/intent/signal_collector.py
backend/intent/hypothesis_builder.py
backend/intent/decision_prompt.py
backend/intent/decision_parser.py
backend/intent/action_planner.py
backend/intent/trace_adapter.py
backend/intent/profile_registry.py
backend/continuation/__init__.py
backend/continuation/models.py
backend/continuation/candidate_collector.py
backend/continuation/decision_prompt.py
backend/continuation/decision_parser.py
backend/continuation/query_rewriter.py
backend/continuation/execution_contract.py
backend/continuation/return_parser.py
backend/continuation/trace_adapter.py
backend/continuation/profile_registry.py
backend/tests/continuation_candidate_regression.py
backend/tests/continuation_decision_regression.py
backend/tests/continuation_subagent_contract_regression.py
backend/tests/intent_signal_regression.py
backend/tests/intent_hypothesis_regression.py
backend/tests/intent_decision_regression.py
backend/tests/intent_profile_registry_regression.py
backend/tests/intent_execution_strategy_regression.py
backend/tests/intent_long_task_escalation_regression.py
backend/tests/orchestration_runtime_assembly_regression.py
backend/tests/orchestration_runtime_dispatch_regression.py
backend/tests/single_agent_runtime_regression.py
backend/tests/continuation_profile_registry_regression.py
backend/tests/continuation_non_file_domain_regression.py
```

### 修改

```text
backend/context_management/resolver.py
backend/context_management/current_turn.py
backend/understanding/task_understanding.py
backend/orchestration/agent_runtime_chain.py
backend/orchestration/runtime_loop/task_run_loop.py
backend/orchestration/runtime_loop/runtime_assembly_builder.py
backend/orchestration/runtime_loop/runtime_assembly_models.py
backend/orchestration/runtime_loop/task_graph_scheduler.py
backend/orchestration/runtime_loop/langgraph_checkpoint_adapter.py
backend/evidence/pdf_worker.py
backend/evidence/structured_data_worker.py
backend/memory_system/runtime_view.py
backend/memory_system/bundle_service.py
backend/context_policy/package_builder.py
backend/tests/agent_main_assembly_semantic_boundary_regression.py
backend/tests/state_memory_context_policy_regression.py
backend/tests/memory_runtime_route_regression.py
backend/tests/system_eval/long_runner.py
storage/orchestration/intent_domain_profiles.json
storage/orchestration/intent_orchestration_profiles.json
storage/orchestration/runtime_lane_profiles.json
storage/orchestration/agent_runtime_profiles.json
storage/orchestration/capability_units.json
storage/orchestration/continuation_domain_profiles.json
```

### 清理

Phase 9 完成后清理：

```text
ContextResolver 中 active_* 直接权威绑定逻辑
TaskUnderstanding 中 bound_pdf_path / bound_dataset_path 对象选择职责
TaskUnderstanding 中把 route hint 当 intent 的职责
TaskRunLoop 中把 tool observation 直接写成当前 turn 权威绑定的路径
TaskRunLoop 中绕过 runtime assembly 直接选择 graph / subagent / tool 的分支
只为旧 state memory binding 存在的回归测试
```

---

## 14. 迁移和回滚规则

### Shadow 模式

默认先运行：

```text
INTENT_LAYER_MODE=shadow
CONTINUATION_LAYER_MODE=shadow
```

行为：

1. 生成 IntentFrame、IntentHypotheses、IntentDecision、RuntimeAssembly candidates、Continuation candidates 和 decision。
2. 记录 trace。
3. 不影响实际执行。
4. 与旧 resolved_bindings、tool route、subagent route 和 graph route 做 diff。

### Cutover 模式

切换：

```text
INTENT_LAYER_MODE=primary
CONTINUATION_LAYER_MODE=primary
```

行为：

1. ContextResolver 使用 IntentDecision / RuntimeAssembly / ContinuationDecision 作为权威裁决来源。
2. state snapshot active_* 只作为候选来源。
3. TaskRunLoop 执行 RuntimeAssembly，不再自行重判 route。
4. 子 Agent 必须消费 intent 摘要、handoff contract 和 continuation contract。
5. TaskGraph Scheduler 只接收 `graph_coordination_run` runtime spec。

### Rollback 模式

保留短期回滚：

```text
INTENT_LAYER_MODE=legacy
CONTINUATION_LAYER_MODE=legacy
```

仅用于紧急恢复。Phase 9 通过后删除 legacy 路径。

---

## 15. 成功标准

短期成功：

1. 最新六十轮长跑中的 `turn 11 / 13 / 44 / 47 / 57` 不再因 `active_dataset` 失败。
2. `turn 57` 不再把 PDF binding 带入 structured data task。
3. `turn 25 / 52` 称呼偏好通过长期记忆召回。
4. `turn 53` 信息不足表达符合事实原则。
5. 新任务、显式切换、RAG 检索、记忆召回不再被误判为普通 follow-up。
6. 普通复杂任务不再因为缺少任务图而退化为单轮回答。

中期成功：

1. PDF、dataset、bundle、memory recall、RAG retrieval、single agent long run、workflow graph 的意图判断和 runtime assembly 都有统一 trace。
2. 主 Agent 长任务、子 Agent 委派、后台任务和 TaskGraph coordination 都有稳定 runtime assembly / runtime spec。
3. 主 Agent 委派和子 Agent 回传有稳定协议。
4. 长跑耗时不因意图裁决、编排组装和续接裁决明显增加。

长期成功：

1. State Memory 回到记忆职责，不再承担执行绑定。
2. Intent Recognition Layer 成为 Agent 判断力增强层，可服务主 Agent、自主长任务、任务图、工作台和多 Agent 协作。
3. 编排系统自身成为通用 Agent 能力和运行模式组装机制。
4. Continuation Layer 成为 Intent Layer 下的通用续接能力。
5. Agent 能自然理解用户动作和 follow-up，但执行层仍能审计它为什么这样理解。
6. 新增能力域只需要注册 intent / orchestration / continuation profile 和 capability unit，不需要修改核心裁决代码。

---

## 16. 首轮实施记录

实施日期：2026-05-20

本轮已完成主链路可执行切换，不新增“工厂层”，仍由现有编排系统组合 Agent、RuntimeLane、Capability、Skill 和 Contract。

已落地内容：

1. 新增 `backend/intent/*`，把当前 turn 的动作识别拆成 `IntentFrame`、`IntentDecision` 和 `runtime_assembly_hint`。
2. 新增 `backend/continuation/*`，把 state memory / restore data 降级为候选证据，并通过 `ContinuationDecision` 生成当前 turn 的权威续接选择。
3. `ContextResolver` 不再把 `state_snapshot.context_slots.active_*` 直接提升为权威 `resolved_bindings`；权威来源只允许 explicit input 或 `continuation_decision`。
4. `TaskUnderstanding` 只接收 continuation 选中的 active bindings，并增加当前用户语义对齐，避免 stale PDF / stale dataset 覆盖当前 turn。
5. 新增 `storage/orchestration/intent_domain_profiles.json` 和 `storage/orchestration/continuation_domain_profiles.json`，首批覆盖 dataset、pdf、knowledge、memory、task_bundle、workflow_graph、long_task。
6. 新增 `backend/orchestration/delegation_protocol.py`，明确主 Agent 委派、子 Agent 回传、主 Agent 收口的标准通信协议。
7. `TaskSpec` 中写入 `agent_communication_protocol`，`RuntimePromptContract` 中写入通信 guardrail，`delegate_to_agent` 请求会携带协议和 expected output contract。
8. `AgentDelegationResult` 增加 `consumed_handles` 与 `produced_handles`，子 Agent 回传后主 Agent 可按证据包收口。
9. 补强 `rag-skill`、`pdf-analysis`、`structured-data-analysis` 的委派、回传和主 Agent 收口说明，并刷新技能注册快照。
10. 增加回归覆盖：turn57 数据子集续接、PDF 指代续接、RAG 不退化成 `search_text`、单 Agent 长任务不误触发图任务、显式图式协作才进入 graph coordination。

已验证命令：

```bash
python -m pytest backend/tests/intent_continuation_layer_regression.py backend/tests/context_management_current_turn_regression.py backend/tests/task_understanding_regression.py backend/tests/agent_main_assembly_semantic_boundary_regression.py backend/tests/followup_execution_contract_runtime_regression.py backend/tests/query_runtime_runtime_loop_regression.py backend/tests/orchestration_runtime_spec_regression.py backend/tests/skill_runtime_regression.py backend/tests/skills_registry_regression.py backend/tests/memory_runtime_route_regression.py backend/tests/state_memory_context_policy_regression.py backend/tests/search_policy_runtime_regression.py backend/tests/task_graph_permission_boundary_regression.py -q
```

结果：`48 passed`

```bash
python -m pytest backend/tests/agent_delegation_permission_regression.py backend/tests/agent_evidence_packet_regression.py backend/tests/main_agent_natural_delegation_regression.py backend/tests/orchestration_agent_management_regression.py backend/tests/skill_policy_resolver_regression.py backend/tests/skill_runtime_integration_regression.py -q
```

结果：`43 passed`

```bash
python -m pytest backend/tests/orchestration_cutover_regression.py backend/tests/runtime_loop_budget_regression.py backend/tests/model_response_runtime_regression.py backend/tests/orchestration_runtime_spec_regression.py -q
```

结果：`20 passed`

待长跑验证命令：

```bash
python backend/tests/system_eval/long_runner.py --scenario sixty-turn-real-user-marathon --output-dir output/test_runs/<run-id>
```
