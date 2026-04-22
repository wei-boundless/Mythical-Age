# 输出主链与 Canonical Answer 收口计划书

> 目的：针对当前系统中 `done.content`、session assistant content、task summary、memory projection 共用同一段“未分型文本”的问题，基于当前项目真实代码结构，参考 Claude Code / OpenAI Agents SDK / AutoGen / PydanticAI 的共同设计原则，完成一次“输出主链收口”的专项规划。  
> 本计划书不追求迁移到某个框架，而是要在保留当前 runtime 主体的前提下，建立一条明确、可验证、可持续扩展的 `canonical answer` 主链。

---

## 1. 这份计划书的定位

这不是：

- 再给 `output_boundary.py` 加几条正则
- 再调一版 prompt，让模型少说“我来检索”
- 再给长测试补几个 `contains` 断言

这份计划书要解决的是更底层的问题：

> 当前系统还没有一条真正统一的“用户可见答案主链”。

现在项目里，至少有下面几条路径都可能把文本推进最终答案：

1. `agent.astream(messages)` 的流式 token 文本
2. `updates` 中 `ai` message 的文本
3. direct tool 的 `tool_content`
4. follow-up / compound / binding_ref 的汇总文本
5. `output_boundary` 的字符串清洗结果
6. `last_ai_message` 的 fallback

这些路径最后都可能汇聚到：

- `done.content`
- session assistant content
- `TaskSummaryRef.summary`
- session memory projection
- long test `final_text()`

但当前并没有一个单独的“最终答案决策层”来决定：

- 哪些文本只是过程
- 哪些是工具原始结果
- 哪些是可展示摘要
- 哪些才是最终答案

因此，这份计划书的目标不是“再清洗文本”，而是：

1. 统一输出候选的内部表示
2. 统一 canonical answer 的判定入口
3. 统一 `done.content` 作为投影字段而非自由写入字段
4. 统一 session / memory / task summary 只消费 canonical answer
5. 统一 raw tool output、debug、progress 留在非可见轨道

---

## 2. 先给结论：当前问题的本质不是 RAG 失效，而是输出主链失控

当前长场景暴露的问题表面上看是：

- RAG 首轮没有答出“三类风险”
- PDF follow-up 吐出 browse dump
- 工具过程文本进入最终答案

但从代码角度看，本质问题更统一：

### 2.1 `done.content` 现在承担了过多职责

当前 [backend/query/runtime.py](/D:/AI应用/langchain-agent/backend/query/runtime.py) 中的 `done.content` 同时扮演：

- SSE 最终输出
- 非流式 API 返回值
- assistant persisted message 的 fallback 来源
- long test `final_text()` 的唯一来源
- session/memory projection 的上游真相

结果是：一旦 `done.content` 混入过程文本，整条链都脏。

### 2.2 当前系统把“文本存在”误当成“答案存在”

现状是：

- 模型说“我来检索……”
- output boundary 认为这是一段非空文本
- runtime 把它视作 final answer
- session 存下它
- 下一轮 follow-up/memory 继续消费它

也就是说，当前系统缺的不是“更多文本”，而是“文本类型判定”。

### 2.3 当前输出边界过于靠后，且只是字符串级

[backend/query/output_boundary.py](/D:/AI应用/langchain-agent/backend/query/output_boundary.py) 现在主要做：

- internal protocol marker 剔除
- pseudo tool call 剔除
- procedural line trimming

它有价值，但它仍然是在“字符串已经生成之后”做补救。

而参考的主流框架的共同点是：

- 先分事件/消息类型
- 再决定哪些可见
- 最后才做少量显示层清理

### 2.4 当前 session / memory 层没有被 canonical answer 保护

当前 [backend/runtime/session_store.py](/D:/AI应用/langchain-agent/backend/runtime/session_store.py) 仍只存：

- `role`
- `content`
- `tool_calls`

没有“这段 content 是 final answer 还是 progress text”的内部语义。

因此，一旦 runtime 选错答案，session 和记忆层无从纠偏。

---

## 3. 参考主流框架后，真正值得借鉴的不是 SDK，而是设计原则

这轮我们不迁移框架，但要明确借鉴哪些原则。

### 3.1 Claude Code：类型先于显示

借鉴点：

- internal tool chatter 不进入用户可见轨道
- tool result / summary / assistant turn 是不同消息种类
- bridge/export/title 都不会把 tool/meta/compact 内容当普通 assistant prose

不直接采用：

- 不照搬完整 transcript/message schema
- 不重做 bridge/REPL/transport 系统

### 3.2 OpenAI Agents SDK：result/state 与流事件分离

借鉴点：

- stream 中有事件，最终才有 result
- 最终结果对象不等于任意一段流式文本

不直接采用：

- 不迁移到 Agents SDK runtime
- 不引入整个 run state / item protocol

### 3.3 AutoGen：event/message/final response 分轨

借鉴点：

- `run_stream()` 的中间 event 和最终 `TaskResult` 是不同层
- tool 运行与最终响应之间有明确汇总边界

不直接采用：

- 不让 agentchat 成为项目主编排层

### 3.4 PydanticAI：轻量 processor + validation

借鉴点：

- 轻量消息处理器
- 输出分类与结果验证
- tool call/result pairing 这种结构约束优先于 display patch

不直接采用：

- 不替换现有 model runtime

### 3.5 综合结论

本项目这轮最适合采用的是：

- Claude Code 的“类型先于显示”
- OpenAI Agents 的“final result 独立于 stream text”
- AutoGen 的“event 与 final response 分轨”
- PydanticAI 的“processor + validation + light schema”

---

## 4. 当前项目的真实约束

方案必须服从下面这些现实约束。

### 4.1 外部契约约束

[backend/api/chat.py](/D:/AI应用/langchain-agent/backend/api/chat.py) 当前非流式接口只认：

- `done.content`

[backend/tests/system_eval/execution_core.py](/D:/AI应用/langchain-agent/backend/tests/system_eval/execution_core.py) 当前长测最终文本也只认：

- `done.content`

所以不能一下子取消 `done.content`。

### 4.2 持久化约束

[backend/runtime/session_store.py](/D:/AI应用/langchain-agent/backend/runtime/session_store.py) 当前只支持扁平 assistant message：

- `role`
- `content`
- `tool_calls`

所以这轮不适合直接切换成复杂 typed transcript 存储。

### 4.3 当前 runtime 结构约束

[backend/query/runtime.py](/D:/AI应用/langchain-agent/backend/query/runtime.py) 目前是：

- 先流式收 token
- 再收 `updates`
- 最后由 `AssistantOutputBoundary` 生成 visible text
- 再把 visible text 写入 `done.content`

所以最合理的改法，不是推翻 runtime，而是在 runtime 内部补一层输出分类与决策。

### 4.4 当前 memory 依赖约束

session memory / durable extraction 当前会继续吃：

- `main_context`
- `task_summary_refs`
- persisted assistant messages

所以 canonical answer 的稳定性直接关系到 memory 质量。

---

## 5. 本轮总目标架构

本轮不改外部 API 契约，只在内部建立 5 层输出主链。

### 5.1 Output Candidate Layer

职责：

- 采集本轮可能进入最终答案的所有候选文本

候选来源：

- stream text
- ai update text
- tool visible summary
- tool raw output
- follow-up assembled summary
- fallback answer

### 5.2 Output Classification Layer

职责：

- 把候选文本判定为：
  - `progress_text`
  - `tool_raw_output`
  - `tool_visible_summary`
  - `answer_candidate`
  - `fallback_answer`

### 5.3 Canonical Answer Decision Layer

职责：

- 在当前 turn 内只产生一个 canonical answer

优先级：

1. 明确 answer candidate
2. summary-first tool visible summary
3. route-aware fallback answer
4. 禁止把 progress/raw output 直接提升为 canonical answer

### 5.4 Projection Layer

职责：

- 把 canonical answer 投影到现有契约字段

只允许投影到：

- `done.content`
- session assistant `content`
- `TaskSummaryRef.summary`
- memory projection 可见部分

### 5.5 Debug / Evidence Layer

职责：

- 保存不进入 canonical answer 的其他输出

包括：

- stream raw text
- tool raw output
- debug flags
- fallback 选择原因

---

## 6. 这轮要一起搭起来的相关结构

这部分是本计划书最重要的部分。

### 6.1 OutputCandidate：候选输出对象

建议新增：

- `candidate_id`
- `channel`
- `text`
- `source`
- `route`
- `tool_name`
- `task_id`
- `priority_hint`
- `metadata`

其中 `channel` 只允许有限集合：

- `progress_text`
- `tool_raw_output`
- `tool_visible_summary`
- `answer_candidate`
- `fallback_answer`

### 6.2 OutputDecision：最终输出决策对象

建议新增：

- `canonical_answer`
- `selected_channel`
- `selected_source`
- `rejected_candidates`
- `leak_flags`
- `fallback_reason`

这使 `done.content` 从“生产字段”变成“投影字段”。

### 6.3 route-aware fallback policy

必须按 route 分开：

- `rag`：无证据时输出“无法基于当前本地知识库可靠回答”
- `tool/pdf`：优先 summary-first，不直接透传 browse dump
- `memory`：不能输出“我来回忆一下”，必须给结论或明确无法确认
- `followup`：不能退化成过程叙述

### 6.4 canonical persistence policy

必须明确：

- persisted assistant content 只写 canonical answer
- raw tool output 只留在 tool event / task result / debug
- progress_text 不进入 persisted assistant content

### 6.5 task summary 生成策略

direct tool / follow-up / compound subset 统一要求：

- `TaskSummaryRef.summary` 来自 canonical answer 或 summary-first output
- 不允许把 raw tool output 直接截断后塞进 summary

### 6.6 debug trace 与用户可见答案分离

必须让：

- trace/debug 中可保留 raw/progress
- 但 `done.content`、session、memory 不可见

---

## 7. 分阶段实施计划

### Phase 0：护栏与基线观测

目的：

- 先把“什么不该成为最终答案”变成门禁

要做：

1. 为 RAG 首轮场景补回归：
   - 不允许 `done.content` 包含：
     - `我来检索`
     - `让我先`
     - `search_knowledge`
2. 为 PDF follow-up 补回归：
   - 不允许 `done.content` 直接是 raw browse dump
3. 增加结构断言：
   - session persisted assistant content 必须等于 canonical answer

退出条件：

- 当前错误模式可被稳定捕获

### Phase 1：引入内部输出模型

目的：

- 给 runtime 增加一层内部输出对象，不改变外部契约

要做：

1. 新增 `OutputCandidate`
2. 新增 `OutputDecision`
3. runtime 内部收集候选输出，而不是直接写 `final_content`

退出条件：

- runtime 内部能看到候选输出分桶

### Phase 2：建立分类层

目的：

- 让系统先判断“这是什么文本”，再判断“要不要给用户”

要做：

1. 新增 `output_classifier.py`
2. 将 stream text / ai update / tool output 分类
3. procedural / progress / raw output 不再默认进入最终答案

退出条件：

- “我来检索……” 被稳定判为 `progress_text`

### Phase 3：建立 canonical answer 决策层

目的：

- 保证每轮只有一个 canonical answer

要做：

1. 新增 `output_selector.py` 或把选择逻辑合入 `output_boundary.py`
2. route-aware fallback
3. answer candidate / tool visible summary / fallback 三选一

退出条件：

- `done.content` 不再直接来自 `last_ai_message`

### Phase 4：投影收口

目的：

- 让 `done.content`、session persistence、task summary 都只吃 canonical answer

要做：

1. `done.content = canonical_answer`
2. persisted assistant content = canonical answer
3. `TaskSummaryRef.summary` 改为 canonical answer / summary-first answer

退出条件：

- session assistant 不再保存过程文本

### Phase 5：旧路径清理与门禁固化

目的：

- 清理会把系统拖回旧逻辑的 fallback

要做：

1. 收紧 `last_ai_message` fallback
2. 收紧 raw tool output 直出路径
3. 长测门禁升级为“答案质量门禁”

退出条件：

- 输出主链只剩 canonical answer 一条主路

---

## 8. 逐文件实施清单

### 8.1 [backend/query/runtime.py](/D:/AI应用/langchain-agent/backend/query/runtime.py)

本轮职责：

- 输出主链编排入口

要改：

- stream / update / tool output 改为先进入 candidate collection
- 取消 `last_ai_message -> done.content` 的直接兜底
- `done.content` 改为 `OutputDecision.canonical_answer`
- persisted assistant content 只用 canonical answer

### 8.2 [backend/query/output_boundary.py](/D:/AI应用/langchain-agent/backend/query/output_boundary.py)

本轮职责：

- 从字符串清洗器升级为输出边界协调器

要改：

- 保留 sanitize 逻辑，但降级为辅助
- 增加候选输出收集
- 增加 canonical answer 构造入口

### 8.3 新增 [backend/query/output_models.py](/D:/AI应用/langchain-agent/backend/query/output_models.py)

本轮职责：

- 定义内部输出结构

建议包含：

- `OutputChannel`
- `OutputCandidate`
- `OutputDecision`

### 8.4 新增 [backend/query/output_classifier.py](/D:/AI应用/langchain-agent/backend/query/output_classifier.py)

本轮职责：

- 负责分类，不负责最终选择

要改：

- procedural/progress 判定
- raw tool output 判定
- visible summary 判定
- route-aware answer candidate 判定

### 8.5 [backend/query/answer_assembler.py](/D:/AI应用/langchain-agent/backend/query/answer_assembler.py)

本轮职责：

- 保持 summary-first 装配

要改：

- 保证 follow-up / direct tool 场景装配来源是 canonical summary
- 不能无条件回退到 raw content

### 8.6 [backend/runtime/session_store.py](/D:/AI应用/langchain-agent/backend/runtime/session_store.py)

本轮职责：

- 保持扁平格式不变，但只持久化 canonical answer

要改：

- 当前不扩 schema
- 但 runtime 写入前必须保证内容已 canonical

### 8.7 [backend/tests/query_runtime_route_guard_regression.py](/D:/AI应用/langchain-agent/backend/tests/query_runtime_route_guard_regression.py)

本轮职责：

- 覆盖输出主链回归

要补：

- process text 不得成为 final answer
- raw tool output 不得直接成为 final answer
- empty retrieval 必须触发 canonical fallback

### 8.8 [backend/tests/system_eval/long_scenarios.py](/D:/AI应用/langchain-agent/backend/tests/system_eval/long_scenarios.py)

本轮职责：

- 提升长测语义门禁

要补：

- `response.nonempty` 升级为：
  - 不含 `我来检索`
  - 不含 `search_knowledge`
  - 不含显式工具协议/过程文本

### 8.9 [backend/tests/system_eval/long_runner.py](/D:/AI应用/langchain-agent/backend/tests/system_eval/long_runner.py)

本轮职责：

- 暴露 canonical answer 相关诊断字段

要补：

- `done.content` 与 persisted assistant 是否一致
- 是否命中 fallback
- 是否出现 leak flags

---

## 9. 每阶段必须锁住的流程细节

### 9.1 标准 RAG turn

必须是：

`retrieval`
-> `candidate collection`
-> `classification`
-> `canonical answer selection`
-> `done.content`
-> `session persistence`

不能是：

`模型先说一句准备检索`
-> `非空`
-> `done.content`

### 9.2 标准 direct tool turn

必须是：

`tool raw output`
-> `summary candidate`
-> `canonical answer`
-> `done.content`

不能是：

`tool raw output`
-> `done.content`

### 9.3 标准 binding follow-up turn

必须是：

`binding owner hit`
-> `local execution`
-> `tool/raw result`
-> `summary-first answer`
-> `done.content`

不能是：

`binding hit`
-> `browse dump`
-> `done.content`

---

## 10. 回归门禁

### 10.1 结构门禁

- `done.content` 必须来自 canonical answer
- persisted assistant content 必须等于 canonical answer
- raw tool output 不得直接写入 persisted assistant content

### 10.2 语义门禁

- 首轮 RAG 问题不能返回“我来检索……”
- PDF follow-up 不能直接返回 browse dump
- memory/follow-up 问句不能返回“让我先看看……”

### 10.3 长场景门禁

- `done.content` 不含显式过程短语
- `done.content` 不含工具名伪调用
- `done.content` 在无证据场景下仍是 canonical fallback

---

## 11. 本轮明确不做的事

- 不重写 session storage schema
- 不迁移到 LangGraph / AutoGen / Agents SDK
- 不实现完整 Claude Code transcript/message 模型
- 不通过单纯 prompt 调优替代结构修复
- 不继续让 `done.content` 承担自由文本缓冲区角色

---

## 12. 实施顺序建议

严格按下面顺序：

1. `Phase 0`：补门禁
2. `Phase 1`：内部输出模型
3. `Phase 2`：输出分类
4. `Phase 3`：canonical answer 决策
5. `Phase 4`：投影收口
6. `Phase 5`：旧路径清理与门禁固化

执行纪律：

- 默认连续推进，除非遇到真实结构冲突或回归门禁无法解释，否则不中途停下
- 每完成一阶段，先补/跑回归，再进入下一阶段
- 未完成 canonical answer 主链前，不做“回答润色优化”

---

## 13. 最终收口标准

当以下条件同时满足时，本轮才算完成：

1. `done.content` 成为唯一 canonical answer 投影
2. session assistant content 不再存过程文本
3. task summary 不再截 raw tool output 充数
4. RAG / tool / follow-up / compound 都走统一输出主链
5. 长场景中不再出现：
   - `我来检索`
   - `让我先看看`
   - raw browse dump 直接作答

---

## 14. 一句话总结

本轮不是“再清洗一下回答”，而是：

> 在保留当前 API / SSE / session 契约的前提下，把项目里的最终答案从“任意非空文本”升级为“唯一 canonical answer”，并让所有可见层、持久化层、记忆层都只消费这条主链。
