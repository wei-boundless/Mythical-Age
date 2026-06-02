# Claude Code 提示词系统参考与搜索子 Agent 优化计划书

日期：2026-06-02

## 1. 技术源报告

### 1.1 本轮要解决的问题

前一轮实测说明：`web_researcher` 和 `codebase_searcher` 已经能通过 `execute_task_run` 进入专家能力主链路，`result_ref` 也能正常写回；但系统运行质量还不够成熟：

1. `codebase_search` 对自然语言委派提示不敏感。符号型查询能命中正确文件，自然语言查询会被 `Find`、`where`、`records`、`result` 等泛词污染。
2. `DeepSearch` 扩展查询过早。首轮已有足够来源时，仍会继续跑 `official source` / `official announcement`，增加 Tavily 调用和耗时，却不一定提升证据质量。
3. 主 agent 的子 agent 委派规则偏弱。当前 `spawn_subagent` 工具描述只要求 goal/instructions/context refs，但没有像成熟 coding agent 那样明确说明何时不要委派、如何写委派 prompt、结果如何回流、并行搜索如何控制。
4. 搜索专家 profile 有 runtime_config，但缺少统一的 agent 使用契约，导致能力、profile、主 agent prompt、工具描述之间仍靠隐含约定对齐。

本次优化目标不是把 Claude Code 的 prompt 原文搬进项目，而是抽取成熟系统的结构原则，落到本项目已有的 harness / capability_system / profile 架构中。

### 1.2 本项目当前代码依据

本项目已经具备以下基础：

- `backend/harness/runtime/compiler.py`
  - 已将 prompt 分为 `global_static`、`turn_stable`、`turn_context`、`dynamic_projection`、`volatile_user`。
  - `backend/harness/runtime/prompt_segment_plan.py` 已记录 cache role、prefix tier、compression role，并阻止 runtime instance 字段进入稳定前缀。
- `backend/agent_system/profiles/runtime_profile_registry.py`
  - `agent:web_researcher` 已声明 `runtime_kind = "search_agent"`，并只允许 `op.search_agent`、`op.web_search`、`op.fetch_url`。
  - `agent:codebase_searcher` 已声明 `runtime_kind = "codebase_search_agent"`，并只允许本地只读搜索和 git history 读取。
  - 主 agent 已允许搜索专家子 agent，并设定 `summary_and_refs_only` / `observation_refs_only`。
- `backend/harness/loop/specialist_runtime_router.py`
  - 已按 `runtime_kind` 路由到 `DeepSearchCapability` 或 `CodebaseSearchCapability`。
  - router 只路由，不拥有生命周期状态，符合当前架构边界。
- `backend/capability_system/tools/tool_units/subagent_control_tool.py`
  - 已有 `spawn_subagent`、`wait_subagent`、`list_subagents`、`send_subagent_message`、`close_subagent`。
  - 当前 description 太短，不足以教主 agent 写高质量委派任务。
- `backend/capability_system/capabilities/codebase_search/query_planner.py`
  - 已有 stop terms、symbol extraction、preferred roots。
  - 但仍把完整自然语言 query 放入 `text_queries`，并保留过多泛词。
- `backend/capability_system/capabilities/codebase_search/ranker.py`
  - 当前只按 evidence kind 给静态分数，不知道原查询里的关键符号和共现关系。
- `backend/capability_system/capabilities/deepsearch/strategy.py`
  - 当前 `plan()` 会在 `prefer_primary_sources=True` 时预置官方来源扩展 query。
  - `review()` 在 query_queue 有预置任务时会继续跑，容易过度扩展。

### 1.3 Claude Code 本地源码参考

参考材料来自本地目录：

- `D:\AI应用\claude-code-nb-main`
- `D:\AI应用\Claude-Code-Source-Study-main`

关键参考点：

- `D:\AI应用\claude-code-nb-main\constants\systemPromptSections.ts`
  - `systemPromptSection()` 表示 session 内可缓存动态段。
  - `DANGEROUS_uncachedSystemPromptSection()` 表示每轮重算段，并强制写明原因。
- `D:\AI应用\claude-code-nb-main\constants\prompts.ts`
  - system prompt 有明确 static/dynamic boundary，静态内容和动态内容不混放。
- `D:\AI应用\claude-code-nb-main\tools\AgentTool\prompt.ts`
  - Agent 工具 prompt 不只是 schema 描述，而是包含“何时使用 / 何时不要使用 / 如何写委派 prompt / 并行调用 / 结果不可直接给用户”等规则。
  - 对 fresh agent 明确说明：新 agent 没有父会话上下文，必须给完整背景、已知事实、边界和输出要求。
  - 对 fork 明确说明：继承上下文但不要偷看中间 transcript，不要预测未返回结果。
- `D:\AI应用\claude-code-nb-main\utils\forkedAgent.ts`
  - 子 agent context 默认隔离，可变状态默认 clone 或重建；只有基础设施和显式 opt-in 项共享。
- `D:\AI应用\claude-code-nb-main\tools\AgentTool\AgentTool.tsx`
  - Agent 类型选择、permission mode、MCP 要求、worktree/remote 隔离、async/background、result notification 分开处理。
  - Task/Agent 工具是委派入口，不是能力绑定表。
- `D:\AI应用\Claude-Code-Source-Study-main\docs\12-Agent-系统.md`
  - AgentDefinition 包含 agentType、whenToUse、tools、model、permissionMode、maxTurns、background、memory、isolation、requiredMcpServers 等字段。
- `D:\AI应用\Claude-Code-Source-Study-main\docs\13-内置Agent设计模式.md`
  - Explore / Plan 这类只读 agent 使用 prompt 约束 + 工具 denylist 双保险。
  - 专家 agent 的 prompt 要先讲身份、职责、禁止事项、流程和输出格式，而不是写“这是某 runtime 节点”。
- `D:\AI应用\claude-code-nb-main\tools\AgentTool\built-in\exploreAgent.ts`
  - Explore Agent 是快速只读代码搜索专家，核心方法不是“单次关键词搜索”，而是按 thoroughness 要求组合 glob、grep、read 和只读 shell。
  - 它明确要求尽可能并行执行 grep/read，并用工具 denylist 禁止写入和嵌套 agent。
  - 它省略不必要的项目规则上下文，把解释和最终判断交回主 agent，降低搜索子 agent 的上下文负担。
- `D:\AI应用\claude-code-nb-main\tools\WebSearchTool\prompt.ts`
  - WebSearch 明确用于当前信息和知识截止后信息，要求最终回答必须带来源。
  - 对 recent/current 查询要求使用当前年份，避免旧年份污染。
- `D:\AI应用\claude-code-nb-main\tools\WebSearchTool\WebSearchTool.ts`
  - WebSearch 工具是 read-only、concurrency safe、可 defer 的能力。
  - 它通过一次小型模型/tool-use 请求触发服务端 web_search，不把普通 agent 的整个上下文拖入搜索。
- `D:\AI应用\claude-code-nb-main\tools\WebFetchTool\prompt.ts`
  - WebFetch 是 URL + extraction prompt 模式，使用小快模型对网页内容做定向提取。
  - 它带缓存、redirect 处理、只读声明和引用限制，适合 DeepSearch 的“选择性 fetch 后提取”阶段。
- `D:\AI应用\claude-code-nb-main\utils\agenticSessionSearch.ts`
  - 先做确定性候选预筛，再用小模型做语义排序。
  - Prompt 要求“宁可多返回，不要漏掉相关项”，并强制 JSON 输出。
  - 对 DeepSearcher 的启发是：模型应主要用于候选重排/证据判断，而不是替代候选生成。
- `D:\AI应用\claude-code-nb-main\utils\toolSearch.ts` 与 `tools\ToolSearchTool\prompt.ts`
  - 大工具/动态工具定义采用 defer + search 的方式按需加载。
  - 对 DeepSearcher 的启发是：扩展查询和 fetch 也应按需触发，不应在初始 plan 阶段全部展开。

### 1.4 可借鉴原则

本项目应借鉴这些原则，而不是复制 Claude Code 的实现外壳：

1. Prompt 分层应是运行时结构，不是字符串拼接习惯。
2. 子 agent 委派入口必须教主 agent 如何委派，而不只是告诉它工具参数。
3. Fresh specialist agent 默认没有父上下文，必须通过 `goal`、`instructions`、`context_refs`、`expected_outputs` 明确交接。
4. 只读专家必须同时靠 prompt 角色和 operations/tool denylist 约束。
5. 子 agent 的中间过程不应该泄漏进主上下文；主 agent 只消费结果摘要、证据 refs、artifact refs、limitations。
6. 并行搜索应由主 agent 显式发起多个子 agent，不由 TaskRun 隐式 fan-out。
7. 能力选择权归 profile/runtime_kind/router，不归 TaskRun。
8. DeepSearcher 的成熟形态应是候选生成、候选筛选、选择性读取、证据合成、停止判定的闭环，而不是固定追加若干 query。

## 2. 当前差距和裁决

### 2.1 不需要重建的部分

以下部分方向正确，不应推倒：

- `RuntimeCompiler` 的 prompt segment plan。
- `AgentRuntimeProfile` 作为权限、runtime_config、subagent_policy 的权威来源。
- `SpecialistRuntimeRouter` 根据 `runtime_kind` 路由能力。
- `DeepSearchCapability` / `CodebaseSearchCapability` 保留在 `capability_system`。
- `spawn_subagent` / `wait_subagent` 作为主 agent 到子 agent 的生命周期工具。

### 2.2 必须优化的部分

以下部分应该直接修：

1. `CodebaseSearchCapability` 的 query planner 和 ranker。
   - 当前自然语言委派提示会污染检索。
   - 应改成符号优先、命令词清理、共现加权、测试/docs 降权。
2. `DeepSearch` 的扩展策略。
   - 当前官方来源扩展在 plan 阶段过早入队。
   - 应改成首轮核心查询后，根据证据缺口再追加官方/日期/未知项查询。
3. `SubagentControlTool` 的工具描述。
   - 需要补充成熟 agent 委派规则：何时用、何时不用、如何写 prompt、如何并行、如何等待和总结。
4. 主 agent work role prompt。
   - 需要明确：搜索类问题先判断是 web / codebase / knowledge / memory / pdf；如果拆分多个独立问题，可以一次发起多个子 agent；不能预测未返回结果。
5. 搜索专家 profile 的元数据契约。
   - 需要将 `when_to_use`、`input_contract`、`output_contract`、`context_policy` 明确化，减少后续 prompt 和工具描述重复。

### 2.3 明确不做的部分

本计划不做以下事情：

- 不把 capability 移到 `runtime`。
- 不把能力绑定写入 `TaskRun`。
- 不恢复 DeepSearch 的 local files / RAG / memory provider。
- 不引入旧兼容 fallback。
- 不做自动隐式 fan-out。并行由主 agent 明确多次 spawn。
- 不沿用 `SoulImageAssetService` 或 soul 系统相关旧逻辑。
- 不照搬外部源码长 prompt。

## 3. 推荐设计方向

### 3.1 目标权责链

```text
User Request
-> Main Agent semantic decision
-> Subagent delegation policy
-> spawn_subagent(goal/instructions/context_refs/expected_outputs)
-> AgentRuntimeProfile(runtime_kind/operations/context policy)
-> SpecialistRuntimeRouter
-> Capability body
-> AgentRunResult/result_ref
-> wait_subagent result projection
-> Main Agent synthesis
```

### 3.2 Prompt 系统设计

保持现有五段 prompt 分层，但强化三类内容：

1. `global_static`
   - 放通用行为规范、工具使用原则、子 agent 委派原则中不随任务变化的部分。
2. `turn_context`
   - 放当前 agent profile 的工作角色 prompt、可用专家 agent 列表、工具/能力边界。
3. `dynamic_projection` / `volatile_user`
   - 只放当前任务事实、runtime projection、用户本轮请求和观察结果。

后续不允许把 task_run_id、turn_id、当前观察结果等 volatile 信息塞入稳定 prompt 段。

### 3.3 子 agent 委派契约

`spawn_subagent` 的输入语义固定为：

- `target_agent_id`：选择专家，不承载能力参数。
- `goal`：一句话说明要回答的问题或要完成的专家任务。
- `instructions`：包含背景、范围、排除项、执行边界、输出要求、失败处理。
- `context_refs`：只传显式 refs，不默认继承父上下文全文。
- `expected_outputs`：明确要 `answer_candidate`、`evidence_refs`、`artifact_refs`、`limitations`、`file:line` 等。

主 agent 规则：

- 搜索一个明确文件或 1-2 个已知文件时，优先自己用 read/search 工具，不启动子 agent。
- 开放式代码定位、架构追踪、跨文件调用链，使用 `agent:codebase_searcher`。
- 当前信息、官方来源、第三方文档、价格/版本/政策等，使用 `agent:web_researcher`。
- PDF 扫描/解析使用 `agent:pdf_reader`。
- 多个独立搜索问题可以在同一行动批次启动多个子 agent。
- 子 agent 未返回前，主 agent 不得编造结论。
- `wait_subagent` 返回结果后，主 agent 负责整合，不把子 agent 原始内部诊断直接丢给用户。

### 3.4 搜索能力算法设计

#### Codebase Search

目标：让自然语言委派提示也能转成高质量代码检索计划。

改造点：

- planner 增加 command stop terms：
  - 英文：find、where、show、locate、trace、record、records、result、results、route、routes、use、uses 等。
  - 中文：帮我、查一下、在哪里、定位、追踪、记录、结果、调用、路由等。
- planner 优先抽取：
  - CamelCase：`SpecialistRuntimeRouter`
  - snake_case：`_finish_specialist_runtime_execution`
  - dotted module：`harness.loop.task_executor`
  - file/path tokens：`backend/harness/loop/task_executor.py`
- planner 不再默认把完整自然语言句子作为最高优先级 `text_query`。
- ranker 接收 plan/query context：
  - exact symbol hit 加权。
  - 多符号共现加权。
  - path token 命中加权。
  - `backend/tests` 只在 query 明确包含 test/regression/测试时进入高权重，否则降权。
  - docs 默认低于 runtime/source 文件，除非 query 明确是设计文档/计划书。

#### DeepSearch

目标：减少无收益扩展查询，让 deepsearch 变成缺口驱动，而不是预置扩展驱动。

改造点：

- `plan()` 初始只入队核心 query，除非 payload 显式传 `queries`。
- `review()` 在首轮后判断：
  - 如果已有足够来源且 primary/official 来源数量满足阈值，停止。
  - 如果缺 primary source，再追加 official source / official announcement。
  - 如果 freshness required 且无日期来源，再追加 latest / release notes date。
  - 如果 distiller 给 unknowns，再追加针对 unknown 的查询。
- 增加 source diversity 判断：
  - 同域名重复不应算多个高质量来源。
  - primary source 阈值按 unique domain / URL 计算。
- fetch 策略保持保守：
  - 只 fetch top official/primary 候选或 distiller 需要的候选。

借鉴 Claude Code 搜索方法后，DeepSearcher 的目标流程固定为：

```text
normalize intent
-> core web query
-> candidate screening / domain de-dup
-> evidence-gap review
-> targeted follow-up queries only when needed
-> selective fetch with extraction prompt
-> source-backed synthesis with mandatory sources
-> stop or report limitations
```

具体规则：

- 支持 `quick` / `medium` / `very_thorough` 搜索强度，但强度只调预算和覆盖面，不改变 web-only 权责。
- 当前性问题自动加入当前年份或 date/freshness 约束，但不对所有问题硬加。
- 官方来源不是默认第二、第三 query；只有 primary/official 证据不足时才追。
- 搜索结果先按 URL/domain/title/content 做轻量筛选，减少重复域名。
- Fetch 只用于高价值候选，不对普通搜索结果全量 fetch。
- Distiller 使用小模型或确定性 distiller 做证据抽取，输出必须带 source URL、claim、confidence、limitations。
- 没有来源时失败，不合成无来源答案。

## 4. 实施计划

### 阶段 1：Codebase Search 质量修复

修改文件：

- `backend/capability_system/capabilities/codebase_search/models.py`
- `backend/capability_system/capabilities/codebase_search/query_planner.py`
- `backend/capability_system/capabilities/codebase_search/ranker.py`
- `backend/capability_system/capabilities/codebase_search/runtime.py`
- `backend/tests/codebase_search_capability_regression.py`

具体任务：

1. 扩展 `CodebaseSearchPlan`，增加 `query_terms` / `required_terms` 或等价字段。
2. 改 planner：
   - 抽取符号和路径优先。
   - 过滤命令词、语法词、低价值泛词。
   - 限制完整原句进入 text query 的条件。
3. 改 ranker：
   - 接收 plan 或 query context。
   - 加 exact symbol / co-occurrence / path affinity 分。
   - 对测试、docs、storage 做查询感知降权。
4. 补回归：
   - 自然语言查询能命中 `specialist_runtime_router.py` 和 `task_executor.py`。
   - 符号型查询保持高命中。
   - 明确 test 查询时测试文件不被错误降权。

完成标准：

- 之前自然语言对比实验 top 8 相关命中从 0 提升到至少 3。
- 符号查询 top 8 相关命中不低于 5。
- 原有 codebase search 回归通过。

### 阶段 2：DeepSearch 自适应扩展

修改文件：

- `backend/capability_system/capabilities/deepsearch/strategy.py`
- `backend/capability_system/capabilities/deepsearch/runtime.py`
- `backend/capability_system/capabilities/deepsearch/models.py`，仅当需要增加阈值配置时修改。
- `backend/tests/search_specialist_split_regression.py`

具体任务：

1. `plan()` 初始 query 缩减为核心 query + payload 显式 queries。
2. 增加 query normalize：
   - current/latest/recent 查询加入当前年份或 freshness intent。
   - 官方/权威类问题保留 official intent，但不预置多个官方 query。
   - 支持 payload `thoroughness`，映射到 max_queries/max_sources/fetch 策略。
3. `review()` 根据 evidence gap 动态追加 official/freshness/unknown follow-up。
4. 增加 candidate screening：
   - URL/domain 去重。
   - primary/official 候选识别。
   - 重复聚合站、低信息摘要、相同标题降权。
5. 增加 selective fetch：
   - 只 fetch top primary/official/high confidence 候选。
   - fetch prompt 必须是 extraction prompt，不让子模型自由扩写。
6. 增加 source-backed synthesis 约束：
   - answer_candidate 必须由 evidence packet 支撑。
   - 无 evidence 时失败并返回 limitations。
7. 补测试：
   - 首轮已足够时不追加 official 扩展。
   - 缺 primary source 时追加 official follow-up。
   - freshness required 时追加 date/release notes follow-up。
   - current/latest 查询会带当前年份或 dated-source intent。
   - fetch 只作用于高价值候选，不全量抓取。

完成标准：

- 前一轮 Tavily 对比实验中，同类查询 deepsearch 不再固定跑满 3 个 query。
- 不降低 evidence count 和 primary/official count。
- search policy / unsupported source / missing operation 三个控制边界继续通过。
- 返回结果始终包含 source URL / evidence refs；无来源不生成完成态答案。

### 阶段 3：子 agent 委派 prompt 与 profile 契约

修改文件：

- `backend/capability_system/tools/tool_units/subagent_control_tool.py`
- `backend/agent_system/profiles/runtime_profile_registry.py`
- 如需要，新增 `backend/agent_system/profiles/specialist_agent_contracts.py`
- 相关 prompt / runtime profile 测试。

具体任务：

1. 增强 `spawn_subagent` 工具 description：
   - 何时使用子 agent。
   - 何时不要使用子 agent。
   - fresh specialist 没有父上下文，必须写完整 brief。
   - 并行使用规则。
   - 等待和结果综合规则。
2. 增强主 agent `work_role_prompt_by_invocation`：
   - 明确 web/codebase/knowledge/memory/pdf 的专家边界。
   - 不允许预测未返回子 agent 结果。
   - 强调结果 refs 和 limitations 是合成依据。
3. 标准化搜索专家 metadata：
   - `when_to_use`
   - `input_contract`
   - `output_contract`
   - `context_policy`
   - `result_policy`
4. 不把长 prompt 分散复制到多个 profile；能由 helper 生成的契约由 helper 生成。

完成标准：

- runtime catalog 能展示专家 agent 的使用条件和输出契约。
- 主 agent prompt 中有明确子 agent 委派规则。
- 子 agent 工具 schema/description 不携带 runtime 实例字段。

### 阶段 4：提示词分段治理增强

修改文件：

- `backend/harness/runtime/prompt_segment_plan.py`
- `backend/harness/runtime/compiler.py`
- 相关 prompt segment 测试。

具体任务：

1. 保持现有分段，不重写 compiler。
2. 增加“volatile reason”审计：
   - 动态/volatile 段必须带来源或 volatility reason。
   - 高风险 uncached prompt 需要可追踪原因。
3. 确认 agent list / specialist list 放在 session/task 稳定段，不放 volatile 段。

完成标准：

- prompt manifest 能看出 agent 委派规则位于稳定段。
- 动态段继续有 dynamic context report。
- 不出现 task_run_id、turn_id 等 runtime instance 字段进入稳定前缀。

### 阶段 5：实测与对比实验

命令范围全部走 CLI/backend，不走前端。

实验组：

1. `codebase_search` 自然语言 vs 符号查询。
2. `agent:codebase_searcher` 通过 `execute_task_run` 的真实主链路。
3. `single_search` vs `deepsearch` Tavily 对比。
4. `agent:web_researcher` 通过 `execute_task_run` 的真实主链路。
5. 控制边界：
   - policy block web。
   - unsupported source。
   - missing operation。
6. 并行控制实验：
   - 父 agent 同时 spawn web + codebase 两个独立搜索子 agent。
   - 验证 wait/list 只返回各自 result_ref，不泄漏中间诊断到主上下文。

验收指标：

- 自动化测试全部通过。
- 自然语言 codebase 查询 top 8 相关命中至少 3。
- DeepSearch 对已有足够证据的查询减少无收益扩展。
- 专家子 agent result_ref、limitations、evidence_refs 可被 wait_subagent 消费。
- 没有新增 capability 到 TaskRun 的绑定字段。

## 5. 文件级执行清单

### 必改

- `backend/capability_system/capabilities/codebase_search/query_planner.py`
  - 清理自然语言命令词。
  - 增强符号/path/module 提取。
  - 输出查询上下文。
- `backend/capability_system/capabilities/codebase_search/ranker.py`
  - 从静态类型评分改为查询感知评分。
- `backend/capability_system/capabilities/codebase_search/runtime.py`
  - 将 plan 传给 ranker。
- `backend/capability_system/capabilities/deepsearch/strategy.py`
  - 从预置扩展改为 evidence-gap 扩展。
- `backend/capability_system/capabilities/deepsearch/web_text.py`
  - 如当前能力不足，补 URL/domain/title/content 的轻量规范化。
- `backend/capability_system/capabilities/deepsearch/evidence_builder.py`
  - 确认证据包包含 source URL、claim、confidence、limitations。
- `backend/capability_system/tools/tool_units/subagent_control_tool.py`
  - 增强工具描述，教主 agent 正确委派。
- `backend/agent_system/profiles/runtime_profile_registry.py`
  - 增加/规范搜索专家 metadata 和主 agent 委派 prompt。

### 可能新增

- `backend/agent_system/profiles/specialist_agent_contracts.py`
  - 集中定义专家 agent 的 when_to_use / input_contract / output_contract。
  - 避免 metadata 里重复长文本。

### 测试

- `backend/tests/codebase_search_capability_regression.py`
- `backend/tests/search_specialist_split_regression.py`
- `backend/tests/subagent_control_regression.py`
- `backend/tests/specialist_runtime_router_regression.py`
- 如新增 metadata helper，则新增或扩展 runtime profile/catalog 测试。

## 6. 风险控制

1. 避免 prompt 变长导致 cache 退化。
   - 委派规则应放稳定段，避免每轮重算。
2. 避免 ranker 过拟合单个实验。
   - 使用通用信号：符号、路径、共现、source/test/doc 类型。
3. 避免 DeepSearch 漏查。
   - 只有证据充足才早停；缺 primary/freshness/unknown 时继续扩展。
4. 避免子 agent 结果被误当用户可见最终答复。
   - `wait_subagent` 结果由主 agent synthesis，保留 limitations。
5. 避免旧链路复活。
   - 不保留 local_files/RAG/memory 到 DeepSearch 的 fallback。

## 7. 自审结论

本计划没有发现必须先向用户确认的架构歧义：

- 能力本体仍在 `capability_system`。
- 能力选择仍由 profile/runtime_kind/router 决定。
- `TaskRun` 不承担 capability binding。
- 搜索专家是 fresh specialist，不做隐式 fork。
- 并行搜索由主 agent 显式 spawn，不做隐藏 fan-out。
- 旧 DeepSearch 非 web provider 不恢复。

建议执行顺序：先做阶段 1 和阶段 2，因为它们直接修复实测质量问题；再做阶段 3 和阶段 4，提升主 agent 委派和 prompt 系统治理；最后按阶段 5 复测。
