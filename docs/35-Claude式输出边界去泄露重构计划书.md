# Claude式输出边界去泄露重构计划书

> 目的：针对长场景中暴露出的 `</think>`、`<tool_call>`、`**工具调用:**`、工具协议文本泄露到用户答案、session history、hot truth window、session preview 的问题，重新梳理主线程输出链，而不是继续在各处追加字符串补丁。
>
> 本计划书严格对照：
>
> - [docs/06-上下文管理.md](/D:/AI应用/langchain-agent/docs/06-上下文管理.md)
> - [docs/08-Thinking-与推理控制.md](/D:/AI应用/langchain-agent/docs/08-Thinking-与推理控制.md)
> - [docs/11-命令系统.md](/D:/AI应用/langchain-agent/docs/11-命令系统.md)
> - [docs/14-任务系统.md](/D:/AI应用/langchain-agent/docs/14-任务系统.md)
> - [docs/23-Memory系统.md](/D:/AI应用/langchain-agent/docs/23-Memory系统.md)
> - [docs/25-架构模式总结.md](/D:/AI应用/langchain-agent/docs/25-架构模式总结.md)
> - [docs/32-Claude式记忆召回与主线程去污逐文件执行清单.md](/D:/AI应用/langchain-agent/docs/32-Claude式记忆召回与主线程去污逐文件执行清单.md)
> - [docs/34-Claude式Follow-up句柄续接修复计划书.md](/D:/AI应用/langchain-agent/docs/34-Claude式Follow-up句柄续接修复计划书.md)
>
> 同时参考 Claude Code 已验证的几条纪律：
>
> - thinking / tool protocol 不是用户答案的一部分
> - tool 使用走结构化事件，不走自然语言回灌
> - 主线程 working context 只保留 canonical truth，不保留 raw protocol stream
> - debug trace 可以保留原始信息，但不得反向进入模型工作上下文

---

## 1. 这份计划书的定位

这不是“再补一个 `strip('</think>')`”的热修清单，而是一份输出链重构蓝图。

它要解决的是同一类结构性问题在多个位置反复出现：

- 用户最终答案出现 `</think>`、`<tool_call>`、`**工具调用:**`
- assistant 原始协议文本进入 session history
- `hot_truth_window` 从 raw assistant text 里吸收脏内容
- model preview / session preview 被脏历史再次污染
- 后续 turn 在污染后的 working context 上继续推理，造成错误扩散

因此，本计划书的目标是：

1. 明确哪一层负责接收原始模型流
2. 明确哪一层负责把原始流转换成 canonical visible content
3. 明确哪一层可以保留 debug raw trace
4. 明确哪些下游只能消费 canonical truth，不能再读 raw text
5. 给出逐文件改造顺序、删除旧路径的时机和回归门禁

---

## 2. 先给结论：现在真正错的不是“过滤不够”，而是“边界不存在”

当前泄露问题不是某一个正则没写全，而是控制协议和用户内容共用了同一条文本通道。

今天的主链基本是：

`model stream raw text`
-> `runtime 直接拼 final_content_parts`
-> `done.content`
-> `assistant message persisted`
-> `session history`
-> `hot_truth_window`
-> `prompt/session preview`

这条链的结构性错误是：

- 原始流没有被标成 raw/debug
- canonical visible answer 没有独立对象
- session history 假设 assistant content 天然可信
- hot truth window 从 raw history 直接取文本

这违反了你前面已经定下的几条原则：

- main thread 只保留控制面真相
- task / tool / thinking 原始协议不得回流 session/process
- debug 信息默认不进 prompt
- model-visible context 必须小于 debug context

也就是说：

> 现在的问题不是“sanitize 不够”，而是“sanitize 被迫承担了本来应该由架构边界承担的职责”。

---

## 3. 当前代码中的真实错误链

这一节只说当前代码的真实职责分布，不做理念推测。

### 3.1 runtime 把 raw stream 当最终答案源

文件：

- [backend/query/runtime.py](/D:/AI应用/langchain-agent/backend/query/runtime.py)

现状：

- `messages` stream 返回的 `chunk.content`
- 直接进入 `final_content_parts.append(text)`
- 后面用 `"".join(final_content_parts)` 组装 `done.content`

问题：

- raw model stream 里可能包含 thinking 尾标记、tool protocol、provider-specific 控制文本
- runtime 直接把它当作用户可见答案源

这意味着 runtime 里目前没有“输出边界”。

### 3.2 updates 事件和 messages 事件没有职责分流

文件：

- [backend/query/runtime.py](/D:/AI应用/langchain-agent/backend/query/runtime.py)

现状：

- `messages` 模式负责 token 文本
- `updates` 模式负责 `tool_calls` 和部分 `ai` message
- 但最终答案优先取 `messages` 的拼接结果，而不是从结构化 `updates` 中重建 canonical answer

问题：

- 这让 runtime 退化成“谁先来文本就信谁”
- 工具事件虽然是结构化的，但没有真正成为主线程的事实源

这与 [docs/11-命令系统.md](/D:/AI应用/langchain-agent/docs/11-命令系统.md) 和 [docs/14-任务系统.md](/D:/AI应用/langchain-agent/docs/14-任务系统.md) 的类型化协议设计方向相反。

### 3.3 assistant 持久化没有 canonical content contract

文件：

- [backend/query/runtime.py](/D:/AI应用/langchain-agent/backend/query/runtime.py)
- [backend/runtime/session_store.py](/D:/AI应用/langchain-agent/backend/runtime/session_store.py)

现状：

- `_build_assistant_messages()` 只清洗了 `tool_calls`
- `content` 仍然是 segment 原始文本
- `SessionStore.append_messages()` 直接把它写入 session history

问题：

- session store 本不该承担协议识别
- 但 runtime 也没有把 canonical visible content 和 raw stream 分开
- 所以 session history 被动接收污染

### 3.4 hot truth window 直接消费 raw session history

文件：

- [backend/context_management/context_controller.py](/D:/AI应用/langchain-agent/backend/context_management/context_controller.py)

现状：

- `_recent_truth_window()` 直接读取 `message.content`
- 只做截断，不做 truth canonicalization

问题：

- 只要历史里已经混入脏 assistant text，hot truth 就会继续回流
- 这不是“session memory 生成错了”，而是 context controller 读错了输入层

### 3.5 session memory 的净化器只是兜底，不是边界

文件：

- [backend/structured_memory/turn_understanding.py](/D:/AI应用/langchain-agent/backend/structured_memory/turn_understanding.py)

现状：

- `_sanitize_message_content()` 只做一般归一化
- `_looks_like_noise()` 擅长整块 JSON、过长噪声、identity block
- 对“正文里混入协议片段”的场景并不是主防线

问题：

- 这里本来就不该承担主修复职责
- 它只能是 working-memory 入口的二次兜底，而不能替代 runtime 的输出边界

---

## 4. 这次重构必须遵守的设计原则

### 4.1 用户可见答案必须有独立真相源

用户可见答案不能再由 raw model stream 直接拼接得到。

必须存在一份独立的 `canonical visible content`，并且：

- `done.content` 来自它
- session assistant message 来自它
- task summary / hot truth / model preview 也只能来自它

### 4.2 raw protocol 只能存在于 debug channel

`</think>`、`<tool_call>`、provider 私有协议、工具中间过渡话术，只允许存在于：

- trace
- debug artifact
- 观测数据

不得进入：

- 用户答案
- session history
- model-visible context

### 4.3 tool 事实必须走结构化事件，不走自然语言反推

tool call / tool result 已经有结构化事件，就不应再依赖模型输出的“我将调用某工具”“工具输出如下”这类自然语言。

这次要把：

- `tool_start`
- `tool_end`
- `tool_result`

作为事实通道，而不是作为说明文字附属品。

### 4.4 session history 只保留 canonical assistant truth

session history 不是 raw transcript dump。

它至少要满足：

- 可被 hot truth 消费
- 可被 session memory processor 消费
- 不会把内部协议带进 working context

所以 assistant content 的写入 contract 必须收紧。

### 4.5 hot truth 是 canonical truth，不是 recent raw text

`hot_truth_window` 的目标是保留“最近仍然有价值的事实”，不是保留“最近原始文本”。

因此它应读取 canonical assistant text，而不是任何 assistant text。

### 4.6 debug 和 model-visible 视图必须继续分层

这次不能为了修泄露，把 debug trace 一起删掉。

正确的做法是：

- debug 继续保留 raw protocol，便于回溯
- model-visible 只保留 canonical truth

这与 [docs/32-Claude式记忆召回与主线程去污逐文件执行清单.md](/D:/AI应用/langchain-agent/docs/32-Claude式记忆召回与主线程去污逐文件执行清单.md) 中“model-visible context 必须小于 debug context”的原则完全一致。

---

## 5. 目标架构：输出边界四通道 + 六步流程

### 5.1 四通道模型

这次重构后，主线程输出链应拆成四条明确通道：

1. `Raw Stream Channel`
   - 输入：provider/langchain 原始文本流
   - 用途：debug trace、观测
   - 禁止进入用户答案和 session history

2. `Tool Event Channel`
   - 输入：`updates` 中的结构化 tool call / tool result
   - 用途：任务事实、事件观测、工具状态
   - 不依赖自然语言“工具调用说明”

3. `Visible Answer Channel`
   - 输入：经 boundary 归一化后的 assistant visible text
   - 用途：`done.content`、assistant persisted message、task summary

4. `Memory Truth Channel`
   - 输入：canonical assistant visible text + user text
   - 用途：session history、hot truth window、session memory projection

### 5.2 六步流程

这次建议采用下面这条六步固定流程：

1. `ingest raw stream`
   - 接收 `messages` 和 `updates`
   - 原始数据进入 boundary，而不是直接进 `final_content_parts`

2. `classify event ownership`
   - 区分 raw text、tool event、ai visible update、debug fragment

3. `assemble canonical segment`
   - 按 segment 生成 canonical visible segment
   - 每个 segment 都有：
     - `raw_text`
     - `tool_calls`
     - `visible_text`
     - `debug_flags`

4. `compose canonical assistant response`
   - 把多个 segment 合并成统一的 canonical assistant response
   - 这是唯一合法的用户答案对象

5. `persist canonical truth`
   - session history 只写 canonical assistant response
   - task summary 只从 canonical content 产出

6. `project memory-visible truth`
   - hot truth / session preview / context package 只消费 canonical truth
   - raw/debug 只进 trace

---

## 6. 技术方法选择

### 6.1 本轮采用的方法

- `dataclass(slots=True)` 建立 runtime 输出边界对象
- 单独的 output boundary 模块，集中处理 assistant 输出归一化
- runtime 改成多通道装配，而不是字符串拼接
- context controller 改成读取 canonical assistant truth
- regression 测试覆盖：
  - response_text
  - session_model_preview
  - hot_truth_window
  - task_summary

### 6.2 本轮不采用的方法

- 不在十几个地方各加一个 `replace('</think>', '')`
- 不把修复主要放在 `turn_understanding.py`
- 不把问题推给 prompt 让模型“少输出”
- 不引入新框架
- 不把 debug trace 一起删掉

### 6.3 为什么这样选

因为当前最缺的不是更强正则，而是协议边界。

如果边界不立起来：

- 你今天拦了 `</think>`
- 明天 provider 改成 `<internal_reasoning>`
- 后天工具协议又换成别的 marker

系统还是会继续泄露。

只有让 raw/debug 与 canonical visible truth 分流，后面 provider 变化才只需要调整一个边界模块。

---

## 7. 核心重构框架

### 7.1 新增统一输出边界模块

建议新增：

- `backend/query/output_boundary.py`

建议模型：

- `AssistantOutputSegment`
  - `raw_text`
  - `visible_text`
  - `tool_calls`
  - `debug_flags`

- `AssistantOutputBoundary`
  - `ingest_stream_text(text)`
  - `ingest_ai_update(content, has_tool_calls)`
  - `ingest_tool_call(tool_name, args)`
  - `ingest_tool_result(tool_name, output)`
  - `finalize_segment()`
  - `build_response()`

- `AssistantOutputResponse`
  - `visible_text`
  - `segments`
  - `tool_calls`
  - `raw_debug_text`
  - `leak_flags`

### 7.2 ownership 约束

这个模块的 ownership 必须明确：

- `runtime` 负责喂原始事件
- `output_boundary` 负责归一化输出
- `session_store` 不做协议修复
- `context_controller` 不做协议修复，只消费 canonical truth

---

## 8. 逐文件执行清单

下面进入正式逐文件清单。

### 8.1 [backend/query/output_boundary.py](/D:/AI应用/langchain-agent/backend/query/output_boundary.py)

当前职责：

- 不存在，本轮新增

新增内容：

- 建立统一的 assistant 输出边界对象
- 统一管理 raw/debug、tool events、visible text 的分流

实现要求：

- 原始流与 canonical answer 分离
- 每个 segment 都可追踪
- 支持 fallback，但 fallback 也必须走 canonicalization

验收标准：

- 任意 raw stream 中混入 `</think>` 或 `<tool_call>`，都不会直接进入 `visible_text`

### 8.2 [backend/query/runtime.py](/D:/AI应用/langchain-agent/backend/query/runtime.py)

当前职责：

- 负责模型流式调用、事件转发、assistant 持久化、task summary 生成

现存问题：

- 直接拼接 raw stream 成最终答案
- `_build_assistant_messages()` 没有 canonical content contract
- task summary 与最终答案没有统一 truth source

具体修改：

- 用 `AssistantOutputBoundary` 替换 `final_content_parts`
- `messages` mode 只作为 raw input source
- `updates` mode 继续作为 tool event source
- `done.content` 改成 boundary 的 `visible_text`
- `_build_assistant_messages()` 改成只接收 canonical segment/content
- `_build_single_execution_task_summaries()` 只接收 canonical visible content

删除/废弃旧逻辑：

- `final_content_parts` 作为最终答案真相源的职责
- 依赖 raw segment `content` 直接写入 session 的路径

验收标准：

- 单轮响应中不再出现 `</think>`、`<tool_call>`、`**工具调用:**`
- task summary 与 `done.content` 使用同一 truth source

### 8.3 [backend/runtime/session_store.py](/D:/AI应用/langchain-agent/backend/runtime/session_store.py)

当前职责：

- session history 持久化

现存问题：

- 目前默认信任上游传来的 assistant content

具体修改：

- 不在这里增加协议逻辑
- 但通过类型/调用约束明确：
  - 只允许写 canonical assistant content
- 视情况补注释或 helper path，标明这是 canonical sink

验收标准：

- session store 不再接收 raw protocol text 作为主路径输入

### 8.4 [backend/context_management/context_controller.py](/D:/AI应用/langchain-agent/backend/context_management/context_controller.py)

当前职责：

- 组装 context package，生成 `hot_truth_window`

现存问题：

- `_recent_truth_window()` 直接读取 raw `message.content`

具体修改：

- `hot_truth_window` 改为消费 canonical truth
- 如果历史里存在旧脏消息，controller 可以做保守过滤，但这只是兼容层
- 不再把 recent raw assistant text 直接视为 truth

验收标准：

- `session_model_preview` 和 prompt 里的 `Hot Truth Window` 不含协议标记

### 8.5 [backend/structured_memory/turn_understanding.py](/D:/AI应用/langchain-agent/backend/structured_memory/turn_understanding.py)

当前职责：

- session memory 的消息理解与基础净化

现存问题：

- 这里只能做兜底，不该继续承担主修复职责

具体修改：

- 保留为 second-line defense
- 视需要补充对旧脏历史的兼容性噪声识别
- 但不能把主修复继续堆到这里

验收标准：

- 即使上游已有 canonicalization，这里仍能对残留异常做保守拦截

### 8.6 [backend/tests/query_runtime_route_guard_regression.py](/D:/AI应用/langchain-agent/backend/tests/query_runtime_route_guard_regression.py)

新增测试：

- fake stream 包含 `</think>` 和 `<tool_call>`，最终 `done.content` 仍然干净
- `_build_assistant_messages()` 只持久化 canonical visible text
- task summary 不再包含协议文本

验收标准：

- runtime 层单元测试直接锁住输出边界 contract

### 8.7 [backend/tests/context_management_regression.py](/D:/AI应用/langchain-agent/backend/tests/context_management_regression.py)

新增测试：

- 带脏 assistant history 的场景下，`hot_truth_window` 不应再回显协议文本
- session block / model-visible prompt 不含 `</think>` / `<tool_call>`

验收标准：

- context controller 不再把历史脏文本反向推回 prompt

### 8.8 [backend/tests/system_eval/long_runner.py](/D:/AI应用/langchain-agent/backend/tests/system_eval/long_runner.py)

新增观测：

- 统计：
  - `response_has_internal_protocol`
  - `model_preview_has_internal_protocol`
  - `hot_truth_has_internal_protocol`

验收标准：

- 长场景里可以直接暴露这类泄露，而不是只看 `passed`

---

## 9. 执行顺序

建议严格按下面顺序推进，不要跳步：

### Phase 0：先立 contract，不改业务判断

文件：

- `backend/query/output_boundary.py`
- `backend/query/runtime.py`

目标：

- 先把 canonical visible content 的 contract 建起来
- 不先去改 context controller 或 session memory

退出条件：

- `done.content` 与 persisted assistant message 改为吃 canonical truth

### Phase 1：把 context package 改成消费 canonical truth

文件：

- `backend/context_management/context_controller.py`
- `backend/tests/context_management_regression.py`

目标：

- `hot_truth_window` 不再读 raw assistant text

退出条件：

- session preview / prompt block 不含 internal protocol

### Phase 2：把 session memory 兼容层收口

文件：

- `backend/structured_memory/turn_understanding.py`
- 必要时补相关 regression

目标：

- 对旧历史提供兜底兼容
- 但不把主要逻辑迁进这里

退出条件：

- 旧脏历史不再明显污染新 turn

### Phase 3：跑长场景并补门禁

文件：

- `backend/tests/system_eval/long_runner.py`
- 长场景报告产物

目标：

- 让长测对泄露问题有显式门禁

退出条件：

- `response_text`、`session_model_preview`、`hot_truth_window` 都能自动检测泄露

---

## 10. 每阶段的回归测试清单

### 10.1 runtime contract

- 最终答案不含 `</think>`
- 最终答案不含 `<tool_call>`
- task summary 不含协议文本
- persisted assistant content 不含协议文本

### 10.2 context package

- `hot_truth_window` 不含协议文本
- `session_model_preview` 不含协议文本
- debug trace 仍保留原始信息

### 10.3 long scenario

- `research-brief-and-document-resume`
- `sixty-turn-real-user-marathon`
- 至少补一个 compound 场景回归

### 10.4 兼容性

- follow-up handle 现有路径不能被破坏
- direct tool route 不受影响
- session memory projection 现有回归不能倒退

---

## 11. 这次明确要删掉的旧思路

下面这些思路这次不要再走：

1. 在十几个模块里分别加 `replace('</think>', '')`
2. 把主修复继续堆到 `turn_understanding.py`
3. 让 `context_controller` 一边读 raw text 一边猜哪些算 truth
4. 继续让 `done.content` 来源于 raw token 拼接
5. 继续把 tool protocol 解释文字当作 assistant truth

---

## 12. 最终目标状态

这次收口之后，系统应该变成下面这条链：

`provider raw stream`
-> `runtime output boundary`
-> `canonical visible answer`
-> `session canonical history`
-> `hot truth canonical projection`
-> `model-visible prompt`

同时并行保留：

`provider raw stream`
-> `debug trace`

而不是现在这种：

`provider raw stream`
-> `user answer / session history / hot truth / model preview / debug trace`

---

## 13. 下一步实施建议

如果按这份计划执行，最好的推进顺序是：

1. 先新增 `output_boundary.py`
2. 再改 `runtime.py`
3. 然后改 `context_controller.py`
4. 再补 regression
5. 最后跑长场景验证

也就是：

- 先把输出真相源立起来
- 再把上下游改成消费它
- 最后让测试门禁显式覆盖

这次的核心不是“更会过滤”，而是“谁拥有 canonical visible truth 的裁决权”。
