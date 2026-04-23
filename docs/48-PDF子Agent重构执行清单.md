# PDF 阅读链重构计划书

> 编写日期：2026-04-23  
> 直接输入：`docs/47-长场景实测问题清单与原因定位-20260423.md`  
> 设计约束来源：`docs/设计原则`  
> 目的：把当前 `pdf_analysis` 从“工具驱动的页片段返回链”重构为“能力层 + PDF 阅读子 agent + 主线程收口”的稳定体系。

---

## 1. 目的

本计划书要解决的不是单点 PDF 摘要失败，而是当前 PDF 阅读链整体设计不成立的问题。

本次重构的范围是：

- PDF 交互式阅读任务
- PDF 路径绑定与 follow-up 续接
- PDF 解析、质量门控、阅读策略与输出收口
- PDF 子 agent 与主线程之间的边界

本次重构不包含：

- RAG 主链改造
- 结构化数据链修复
- 通用 compound query 规划
- 全量知识库前处理重建

这次要得到的终态是：

- PDF 基础处理能力归于独立能力层
- PDF 阅读任务交给专门的阅读子 agent
- 主线程只接收稳定 canonical result，不再吞 raw browse dump

---

## 2. 当前断裂点与设计缺口

## 2.1 用户可见断裂

根据 [47-长场景实测问题清单与原因定位-20260423.md](/D:/AI应用/langchain-agent/docs/47-长场景实测问题清单与原因定位-20260423.md)，当前长场景中最优先的问题就是 PDF 跟读链失效：

- “全文总览”经常退化成“已定位到相关页面，但尚未形成可靠摘要”
- 页追问会暴露乱码文本
- 总览命中的页面偏向参考文献、尾页，而不是正文核心页
- follow-up 虽然还能续到同一份 PDF，但续接的是退化结果，不是稳定语义状态

## 2.2 架构层真实缺口

当前系统里，PDF 主链实际上还是：

`task_understanding -> continuation/tool_input resolve -> pdf_analysis_tool -> pdf_analysis.engine -> pdf_analysis.parser -> output_classifier -> fallback`

对应文件：

- [task_understanding.py](/D:/AI应用/langchain-agent/backend/understanding/task_understanding.py)
- [continuation_resolver.py](/D:/AI应用/langchain-agent/backend/query/continuation_resolver.py)
- [tool_input_resolver.py](/D:/AI应用/langchain-agent/backend/query/tool_input_resolver.py)
- [pdf_analysis_tool.py](/D:/AI应用/langchain-agent/backend/tools/pdf_analysis_tool.py)
- [catalog.py](/D:/AI应用/langchain-agent/backend/pdf_analysis/catalog.py)
- [parser.py](/D:/AI应用/langchain-agent/backend/pdf_analysis/parser.py)
- [engine.py](/D:/AI应用/langchain-agent/backend/pdf_analysis/engine.py)
- [output_classifier.py](/D:/AI应用/langchain-agent/backend/query/output_classifier.py)

这条链存在 5 个根缺口：

1. 入口裁决不稳
   - “全文总览 / 核心结论 / 行动建议 / 第二部分约束”这类问题没有被稳定送到正确阅读模式。
2. 能力层与编排层混在一起
   - `engine.py` 同时承担页排序、模式执行、摘要拼接、错误文案生成。
3. 质量门控过弱
   - `parser.py` 只有粗粒度可读性判断，乱码页和参考文献页会进入答案链。
4. 输出契约失真
   - `output_classifier.py` 仍把 `Summary:` 当成 PDF 可靠输出的主要判断口。
5. 主线程吸收了过多 PDF 原始噪音
   - 主线程看到的是 raw tool text 或 fallback 文案，不是稳定结果对象。

---

## 3. 设计依据

## 3.1 本地设计原则

本次方案受以下本地文档约束：

- [12-Agent-系统.md](/D:/AI应用/langchain-agent/docs/设计原则/12-Agent-系统.md)
- [25-架构模式总结.md](/D:/AI应用/langchain-agent/docs/设计原则/25-架构模式总结.md)
- [09-工具系统设计.md](/D:/AI应用/langchain-agent/docs/设计原则/09-工具系统设计.md)
- [06-上下文管理.md](/D:/AI应用/langchain-agent/docs/设计原则/06-上下文管理.md)
- [20-API调用与错误恢复.md](/D:/AI应用/langchain-agent/docs/设计原则/20-API调用与错误恢复.md)
- [23-Memory系统.md](/D:/AI应用/langchain-agent/docs/设计原则/23-Memory系统.md)

从这些文档中提炼出的硬约束是：

1. 默认分层，禁止把绑定、解析、阅读、输出塞进一个运行体。
2. restore 不等于 decide，历史 `active_pdf` 只能恢复候选，不能替代当前轮裁决。
3. fail-closed，不能把不可信结果包装成可用答案。
4. 默认隔离，显式共享，PDF 噪音不能长期污染主线程上下文。
5. 输出必须先 canonicalize，再进入主线程展示。
6. 记忆只保留稳定结论，不保留大段 raw page dump。

## 3.2 外部成熟方案

本次设计只吸收与问题直接相关的成熟机制：

- Microsoft Advanced RAG
  - 文档预处理、抽取、metadata、chunking、索引组织属于 ingestion / capability 层，不属于 agent 层。
  - 来源：<https://learn.microsoft.com/en-us/azure/developer/ai/advanced-retrieval-augmented-generation>
- Anthropic sub-agents
  - 当某类任务会污染主上下文、需要专门 prompt / 工具 / 权限时，适合交给 subagent。
  - 来源：<https://code.claude.com/docs/en/sub-agents>
- LangChain multi-agent
  - specialized agent 负责专门任务，tools 是 agent 的内部执行部件，而不是 agent 的替代品。
  - 来源：<https://docs.langchain.com/oss/python/langchain/multi-agent/index>
- Docling
  - PDF、OCR、表格、阅读顺序恢复应作为独立文档转换/结构恢复能力。
  - 来源：<https://docling-project.github.io/docling/reference/document_converter/>

---

## 4. 取舍分析

## 4.1 方案 A：把全部 PDF 处理都做成子 agent

优点：

- 统一对外口径
- 所有 PDF 逻辑都在一个执行主体下

问题：

- 会把 parser / OCR / ingestion / page tooling 也 agent 化，边界过重
- 不利于底层能力被 RAG、文档转换、缓存构建复用
- 违反成熟系统中“解析能力层”和“交互式阅读层”分离的做法

结论：

- 不采用

## 4.2 方案 B：维持 skill -> tool -> engine 结构，只继续补丁

优点：

- 改动面最小

问题：

- 继续把 `pdf_analysis_tool` 当伪子 agent
- `output_classifier` 仍然需要替 PDF 链补锅
- 主线程仍然会吸收 PDF 原始噪音

结论：

- 不采用

## 4.3 方案 C：能力层 + PDF 阅读子 agent + 主线程接线层

优点：

- 符合本地设计原则与成熟方案
- PDF 解析能力可以被多条链复用
- 阅读任务能在独立上下文里执行，减少主线程污染
- 便于把 follow-up、摘要、页追问、章节追问统一编排

代价：

- 需要新增 agent 协议与结果模型
- 需要拆分 `engine.py` 的职责

结论：

- 采用

---

## 5. 推荐设计

## 5.1 目标架构

重构后，PDF 链固定为三层：

### A. PDF 能力层

归属：

- `backend/pdf_analysis`

职责：

- PDF 解析
- OCR / MinerU / Docling / 本地 fallback 编排
- 页/段/结构质量判定
- 文档结构恢复
- 阅读计划辅助
- 证据与缓存基础设施

这一层不是子 agent。

### B. PDF 阅读子 agent

归属：

- 新增 `backend/pdf_agent` 或等价目录

职责：

- 绑定当前 PDF 对象
- 裁决阅读模式
- 编排能力层
- 组织证据
- 生成稳定摘要与章节/页面回答
- 输出 canonical result

这一层才是 PDF 阅读任务的正式执行主体。

### C. 主线程接线层

归属：

- `backend/understanding`
- `backend/query`
- `backend/tools`
- `backend/structured_memory`

职责：

- 判断是否进入 PDF 阅读域
- 把请求送入 PDF 阅读子 agent
- 接收 canonical result
- 写入最小状态投影

主线程不再直接消费 PDF 原始页片段。

## 5.2 所有权模型

- `skill / route`
  只负责把任务送到 PDF 阅读域
- `pdf_analysis_tool`
  只保留 compatibility facade 角色
- `PDF 阅读子 agent`
  拥有阅读任务的执行权和结果收口权
- `pdf_analysis`
  拥有 PDF 能力层的实现权，不拥有主线程答案呈现权

## 5.3 restore / decide / execute / present 边界

- `restore`
  从 `active_pdf`、history、task snapshot 中恢复候选
- `decide`
  当前轮判断是 browse / deep_read / page_read / section_read
- `execute`
  子 agent 调度 parser、quality gate、reader、summarizer
- `present`
  只用 canonical result 进入主线程输出

不允许：

- restore 直接越权决定当前轮 PDF 身份
- execute 直接把 raw browse dump 当成 present 结果

---

## 5A. 固定执行流

PDF 阅读任务重构后固定为：

`Detect -> Bind -> Route -> Acquire -> Quality Gate -> Read Plan -> Synthesize -> Canonicalize -> Publish -> Persist`

每阶段定义如下：

1. `Detect`
   - 输入：用户消息、当前上下文
   - 输出：进入 PDF 阅读域的决策
   - 所有者：`understanding/query`
   - 禁止：做页排序、做摘要

2. `Bind`
   - 输入：显式 path、history、task snapshot
   - 输出：候选 PDF identity
   - 所有者：PDF 阅读子 agent
   - 禁止：根据旧 `active_pdf` 直接断言当前轮仍是同一 PDF

3. `Route`
   - 输入：query + bound PDF
   - 输出：`browse / deep_read / page_read / section_read`
   - 所有者：PDF 阅读子 agent
   - 禁止：直接生成用户答案

4. `Acquire`
   - 输入：resolved PDF path
   - 输出：ParsedDocument / pages / sections / quality metadata
   - 所有者：`pdf_analysis`
   - 禁止：生成最终答案文案

5. `Quality Gate`
   - 输入：解析结果
   - 输出：可用页、不可用页、降级判定
   - 所有者：`pdf_analysis`
   - 禁止：把坏页伪装成可用页

6. `Read Plan`
   - 输入：route + quality-scored document
   - 输出：覆盖页、章节、证据段
   - 所有者：PDF 阅读子 agent + `pdf_analysis`
   - 禁止：只按 query token 词频排序就直接结束

7. `Synthesize`
   - 输入：read plan + evidence
   - 输出：摘要、行动建议、页结论、章节回答
   - 所有者：PDF 阅读子 agent
   - 禁止：直接抛 raw page snippet

8. `Canonicalize`
   - 输入：内部结果
   - 输出：结构化 canonical result
   - 所有者：PDF 阅读子 agent
   - 禁止：依赖 `Summary:` 字样供主线程猜测

9. `Publish`
   - 输入：canonical result
   - 输出：主线程可消费答案
   - 所有者：`query/runtime`
   - 禁止：绕过 canonical result 直接展示 raw tool output

10. `Persist`
    - 输入：canonical result + binding identity
    - 输出：summary capsule / evidence refs / active_pdf projection
    - 所有者：`structured_memory`
    - 禁止：写入大段 page raw dump

---

## 6. 数据模型变更

## 6.1 新增对象

应新增：

- `PDFReadRequest`
- `PDFRouteDecision`
- `PDFPreparedDocument`
- `PDFReadPlan`
- `PDFCanonicalResult`
- `PDFSummaryCapsule`

## 6.2 降级或退出主职责的对象

需要降级：

- `pdf_analysis_tool`
  - 从用户可见主执行入口降级为 facade
- `engine.py` 直接字符串结果
  - 从正式协议降级为内部兼容残留，最终清理
- `Summary:` 标签协议
  - 从正式成功判据降级为兼容残留

## 6.3 兼容期要求

在新旧路径并存期间：

- 老 `pdf_analysis_tool` 允许存在
- 但必须开始转调新 PDF 阅读子 agent
- 不允许继续给 `engine.py` 新增用户可见输出协议

---

## 6A. 提前锁定的决策

以下决策本计划书直接锁死：

1. `backend/pdf_analysis`
   - 固定为 PDF 能力层目录
2. `backend/pdf_agent`
   - 作为新阅读子 agent 目录
3. `pdf_analysis_tool`
   - 固定为兼容 facade，不再承担核心逻辑
4. `PDFCanonicalResult`
   - 固定为主线程唯一允许消费的 PDF 阅读结果对象
5. `active_pdf`
   - 固定为状态投影，不是当前轮裁决源

---

## 7. 模块改造计划

## 7.1 能力层

涉及：

- [catalog.py](/D:/AI应用/langchain-agent/backend/pdf_analysis/catalog.py)
- [parser.py](/D:/AI应用/langchain-agent/backend/pdf_analysis/parser.py)
- [mineru_client.py](/D:/AI应用/langchain-agent/backend/pdf_analysis/mineru_client.py)
- [engine.py](/D:/AI应用/langchain-agent/backend/pdf_analysis/engine.py)
- [pdf_runtime.py](/D:/AI应用/langchain-agent/backend/pdf_runtime.py)

方向：

- 把 parser / quality gate / read plan helper / evidence helper 从用户可见输出里剥离
- 补稳定的结构化中间模型
- 引入更强页质量判定与参考文献/目录页抑制

## 7.2 子 agent 层

涉及：

- 新增 `backend/pdf_agent/*`

方向：

- 新增 request/result/protocol/runtime 模块
- 建立阅读任务的真正执行入口
- 负责 route / synthesize / canonicalize / persist plan

## 7.3 主线程接线层

涉及：

- [task_understanding.py](/D:/AI应用/langchain-agent/backend/understanding/task_understanding.py)
- [continuation_resolver.py](/D:/AI应用/langchain-agent/backend/query/continuation_resolver.py)
- [tool_input_resolver.py](/D:/AI应用/langchain-agent/backend/query/tool_input_resolver.py)
- [pdf_analysis_tool.py](/D:/AI应用/langchain-agent/backend/tools/pdf_analysis_tool.py)
- [output_classifier.py](/D:/AI应用/langchain-agent/backend/query/output_classifier.py)
- [runtime.py](/D:/AI应用/langchain-agent/backend/query/runtime.py)
- [session_memory.py](/D:/AI应用/langchain-agent/backend/structured_memory/session_memory.py)
- [process_engine.py](/D:/AI应用/langchain-agent/backend/structured_memory/process_engine.py)

方向：

- 改成“检测后进入 PDF 阅读子 agent”
- 收紧主线程只吃 canonical result
- 改写 PDF 状态投影与 follow-up 恢复语义

---

## 8. 分阶段路线

## Phase 1：锁定边界与协议

目标：

- 停止继续在字符串协议上叠补丁

主要变更：

- 锁定三层架构
- 新增 PDF 阅读子 agent 的 request/result 协议
- 确定 `pdf_analysis_tool` 的 facade 身份

完成标准：

- 有正式的 `PDFCanonicalResult`
- 主线程不再以 `Summary:` 作为 PDF 成功主判据

禁止事项：

- 不允许在本阶段优化页排序算法
- 不允许继续扩展旧 `engine.py` 输出格式

## Phase 2：入口裁决与绑定修复

目标：

- 先把“这轮到底要怎么读这份 PDF”判稳

主要变更：

- 提升总览/结论/行动建议到正确模式
- 区分页读与章节读
- 恢复 path 但重新裁决当前轮 mode

完成标准：

- “全文总览”不再默认落入退化 browse
- “第二部分 / 这一章”能稳定进入结构阅读模式

禁止事项：

- 不允许先靠 rerank 或 prompt 补洞

## Phase 3：解析与质量门控重构

目标：

- 让 PDF 文本先可信

主要变更：

- 建立页/段质量画像
- 加入目录页、参考文献页、版权页、OCR 噪声页识别
- 补远端失败 / 本地 fallback / 超时分类

完成标准：

- 乱码页和参考文献页不再稳定跑到总览前列

禁止事项：

- 不允许把坏文本继续包装成“可读页面”

## Phase 4：阅读策略与结果合成

目标：

- 让阅读链产生文档级理解，而不是命中页列表

主要变更：

- browse 变轻摘要
- deep_read 变覆盖型摘要
- page_read 输出页摘要 + 关键句
- 引入 section_read

完成标准：

- “核心结论 / 行动建议 / 第二部分约束”可以稳定回答

禁止事项：

- 不允许继续把 `Relevant pages` 直接给主线程

## Phase 5：主线程收口与状态投影

目标：

- 主线程不再替 PDF 链补锅

主要变更：

- `output_classifier` 改识别结构化结果
- runtime 只消费 canonical result
- structured memory 只存 capsule

完成标准：

- 主线程不再出现旧式 PDF fallback 文案作为正式答案

禁止事项：

- 不允许继续把 page raw dump 写进 session state

## Phase 6：回归、长场景与清理

目标：

- 每修一轮验证一轮，直到长场景稳定

主要变更：

- 补 PDF 专项回归
- 补长场景 PDF 指标
- 清理旧分支与旧协议

完成标准：

- `docs/47` 中 PDF 相关 P1 项显著收敛
- 老兼容路径可明确冻结或删除

禁止事项：

- 不允许在旧新路径混跑但没有链路标记

---

## 9. 文件级清单

### [task_understanding.py](/D:/AI应用/langchain-agent/backend/understanding/task_understanding.py)

- 当前角色：识别 PDF 任务并决定初始模式
- 动作：重写 PDF 阅读模式词表与模式裁决
- 完成条件：总览/行动建议/章节追问不再误进退化 browse

### [continuation_resolver.py](/D:/AI应用/langchain-agent/backend/query/continuation_resolver.py)

- 当前角色：补 PDF 显式引用与 follow-up 续接
- 动作：把恢复与裁决拆开
- 完成条件：恢复 path 不等于自动继承旧 mode

### [tool_input_resolver.py](/D:/AI应用/langchain-agent/backend/query/tool_input_resolver.py)

- 当前角色：补 path
- 动作：升级为补完整 PDF request
- 完成条件：能向新 PDF 阅读子 agent 传结构化请求

### [pdf_analysis_tool.py](/D:/AI应用/langchain-agent/backend/tools/pdf_analysis_tool.py)

- 当前角色：用户可见执行入口
- 动作：降级为 facade
- 完成条件：核心执行逻辑移出 tool

### [catalog.py](/D:/AI应用/langchain-agent/backend/pdf_analysis/catalog.py)

- 当前角色：路径发现和解析
- 动作：保留安全边界，增强 identity 标准化
- 完成条件：路径安全继续成立，绑定 identity 稳定

### [parser.py](/D:/AI应用/langchain-agent/backend/pdf_analysis/parser.py)

- 当前角色：PDF 文本与 segment 抽取
- 动作：补质量画像、远端/本地失败分类、结构化 parse result
- 完成条件：提供可信中间文档对象

### [mineru_client.py](/D:/AI应用/langchain-agent/backend/pdf_analysis/mineru_client.py)

- 当前角色：远端解析客户端
- 动作：补超时、重试、失败原因分类
- 完成条件：主链可知道失败是超时、空结果还是不可用

### [engine.py](/D:/AI应用/langchain-agent/backend/pdf_analysis/engine.py)

- 当前角色：模式执行 + 排序 + 拼字符串
- 动作：拆成阅读计划与证据/摘要辅助
- 完成条件：不再承担最终用户文案拼装职责

### [output_classifier.py](/D:/AI应用/langchain-agent/backend/query/output_classifier.py)

- 当前角色：从工具文本猜测 PDF 成功与否
- 动作：改为识别结构化 canonical result
- 完成条件：移除对 `Summary:` 的单点依赖

### [runtime.py](/D:/AI应用/langchain-agent/backend/query/runtime.py)

- 当前角色：执行主线程收口
- 动作：只接 PDF canonical result
- 完成条件：不再展示 raw browse dump

### [session_memory.py](/D:/AI应用/langchain-agent/backend/structured_memory/session_memory.py)

- 当前角色：写 session 投影
- 动作：只保留 summary capsule / evidence refs / binding identity
- 完成条件：无大段 PDF 原文入记忆

### [process_engine.py](/D:/AI应用/langchain-agent/backend/structured_memory/process_engine.py)

- 当前角色：flow 与状态投影
- 动作：把 `active_pdf` 固定为投影态
- 完成条件：不再越权变成当前轮裁决源

### `backend/pdf_agent/*`

- 当前角色：新增
- 动作：承载 PDF 阅读子 agent 协议、运行时、结果模型
- 完成条件：形成正式阅读子 agent 入口

---

## 10. 验证与验收

必须至少覆盖：

1. 首次打开 PDF 时，总览能直接产出稳定摘要。
2. 页追问能读取正确页，不误页码。
3. 章节追问能进入结构阅读，不退化成普通页命中。
4. 切题后返回仍能续接同一 PDF。
5. MinerU 失败时本地 fallback 可解释。
6. 目录页、参考文献页、乱码页不会稳定进入前排。
7. 主线程不再展示 raw browse dump。
8. session memory 不再保存大段 PDF 原文。

必补测试：

- [pdf_followup_history_regression.py](/D:/AI应用/langchain-agent/backend/tests/pdf_followup_history_regression.py)
- [conversation_scenario_catalog.py](/D:/AI应用/langchain-agent/backend/tests/conversation_scenario_catalog.py)
- [regression_gate.py](/D:/AI应用/langchain-agent/backend/harness/regression_gate.py)

---

## 10A. 迁移与切换规则

旧新路径共存期间，执行以下规则：

1. 冻结规则
   - 不再给旧 `engine.py` 追加新的用户可见协议
2. 兼容规则
   - `pdf_analysis_tool` 暂时保留，但内部转调新子 agent
3. 切换规则
   - 只有当 PDF canonical result 可稳定通过回归后，主线程才完全切到新路径
4. 回退触发
   - 若新路径导致 PDF follow-up 严重失稳，可回退到旧 facade，但不得回退掉新协议模型
5. 最终清理
   - 当新路径稳定后，清掉旧 `Summary:` 协议依赖、旧 raw browse fallback 和兼容字符串分支

---

## 11. 禁止走的捷径

执行过程中明确禁止：

1. 用 prompt 补丁替代结构修复。
2. 用 output_classifier 继续替 PDF 主链补锅。
3. 继续把 parser、route、summary、present 全塞进 `engine.py`。
4. 让 `active_pdf` 重新变成当前轮主裁决源。
5. 在没有链路标识的情况下混用新旧测试结果。
6. 把 PDF 解析能力和 PDF 阅读子 agent 混成同一层。

---

## 12. 预期结果

这次重构完成后，应得到：

1. 更清晰的边界
   - PDF 能力层、阅读子 agent、主线程接线层职责明确
2. 更可信的结果
   - PDF 答案不再依赖 raw browse dump 和 `Summary:` 字样
3. 更稳的 follow-up
   - 页追问、章节追问、总览、行动建议统一进入一个编排体系
4. 更低的主线程污染
   - 主线程只处理结果对象，不长期背负 PDF 原始噪声
5. 更易维护的后续演进
   - 后面接 Docling、MinerU 改造、质量判定增强都能落在能力层，不再冲击主线程协议

---

## 13. 每阶段交付物

### Phase 1

- 代码：PDF 协议模型、agent 入口骨架
- 配置：协议命名与目录约束
- 验证：协议层单测

### Phase 2

- 代码：模式裁决与绑定修复
- 配置：模式词表与阈值
- 验证：follow-up 与章节路由回归

### Phase 3

- 代码：质量画像、失败分类、fallback 改造
- 配置：超时和质量阈值
- 验证：乱码页/参考文献页/超时回归

### Phase 4

- 代码：browse/deep_read/page_read/section_read 正式阅读链
- 配置：阅读模式参数
- 验证：总览/行动建议/章节追问专项回归

### Phase 5

- 代码：canonical result 接线、memory capsule 投影
- 配置：主线程切换开关
- 验证：输出边界与状态投影回归

### Phase 6

- 代码：旧分支清理
- 观测：PDF 质量诊断产物
- 验证：长场景与 PDF 专项回归稳定

这份计划书作为后续 PDF 阅读链重构的正式依据，优先级高于旧的“工具补丁式修复”思路。实际进入编码阶段时，应按本计划书的边界、阶段和禁止事项推进，不得再次回到 `skill -> tool -> engine -> classifier 补锅` 的旧结构。
