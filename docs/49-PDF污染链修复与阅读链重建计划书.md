# PDF 污染链修复与阅读链重建计划书

> 编写日期：2026-04-23  
> 直接输入：`docs/47-长场景实测问题清单与原因定位-20260423.md`、`output/test_runs/20260423-080117-long/*`  
> 目的：针对本轮长场景中 PDF 链路“重构后局部变得更坏”的现象，先追清污染源头，再给出必须连续推进直到收敛的修复路线。

## 0. 最新推进记录（2026-04-23 13:25）

本轮已完成的正式修复，不再停留在 prompt 层，而是已经落实到 PDF 正式链路：

1. 在 `backend/pdf_analysis/parser.py` 与 `backend/pdf_agent/runtime.py` 中补上了结构分类与摘要准入前的正文质量门。
2. 参考文献页、目录页、版权页、坏页已经先被排除在 stable summary 候选集之外。
3. 正文摘要生成前新增了：
   - mojibake 修复
   - OCR/重复噪音清洗
   - 可疑短碎片过滤
   - 版面残留前缀剥离
4. 已通过回归：
   - `backend/tests/pdf_agent_runtime_regression.py`
   - `backend/tests/query_runtime_route_guard_regression.py`
   - `backend/tests/pdf_followup_history_regression.py`
5. 已完成长场景复测：
   - `output/test_runs/20260423-132104-long/`

最新实测结论：

1. 原先主导输出的乱码串，如 `杂芤`、`拼褒捧悼`、`唤纈=凌钨`，已经不再进入 stable summary，也不再被写入 `task_summary_refs/context_ref.summary`。
2. 候选页选择已稳定落在正文页，而不是尾部参考文献页。
3. 当前残余问题已经明显收缩为“版面/OCR残差”，例如：
   - `全球Al治理`
   - `从整体方向看` 前缺少更自然的结构连接
4. 这说明当前阶段已经从“污染链未切断”进入“正文可读性细修”阶段。

因此，后续推进重点不再是“防止脏页进入摘要”，而是：

1. 收敛 `AI/Al` 这类字形级残差。
2. 继续削减 layout residue 对句首的影响。
3. 在不放宽稳定准入门的前提下，进一步提升 stable summary 的自然度。

---

## 1. 当前判断

当前 PDF 链路的问题，不再只是“摘要质量差”，而是已经形成了明确的污染链：

`PDF 原始中间态 -> canonical summary 误收口 -> direct_tool 输出边界失效 -> task summary / main context / session memory 固化 -> follow-up 继续消费污染结果`

这意味着：

1. 当前问题不是单点 prompt 可修复的问题。
2. 当前问题不是单纯 rerank 或页排序问题。
3. 如果不先切断污染链，后面继续调 PDF 阅读策略，只会把脏结果更稳定地写进系统。

本计划书因此不按“先做阅读效果优化”推进，而按以下顺序推进：

1. 先止血
2. 再校正
3. 最后重建

---

## 1.1 设计原则复核结论：问题首先是边界问题

本轮重新对照了以下设计原则文档：

- `docs/设计原则/06-上下文管理.md`
- `docs/设计原则/09-工具系统设计.md`
- `docs/设计原则/12-Agent-系统.md`
- `docs/设计原则/23-Memory系统.md`
- `docs/设计原则/25-架构模式总结.md`

从这些原则回看当前 PDF 链路，可以得到一个比“摘要质量差”更核心的判断：

1. `上下文管理` 要求高噪音中间态不能长期进入主上下文，但当前 PDF 的 raw snippet、兜底话术和错误文本会进入主线程工作上下文。
2. `工具系统设计` 要求 tool 是能力接口，不是最终答案收口器，但当前 direct tool 链把 tool content 直接当成用户可见答案。
3. `Agent-系统` 要求默认隔离、显式共享，但当前 PDF 虽然被当成专门能力调用，却没有真正形成独立工作域和明确共享协议。
4. `Memory系统` 要求只保留稳定、可复用的结果，但当前 PDF degraded 结果仍可能进入 task summary、context summary 和 session memory 投影。
5. `架构模式总结` 要求单一收口源、安全默认值、分层状态边界，但当前 PDF 链路在“执行、展示、状态、记忆”四层都存在混写。

因此，PDF 问题的本质不是“某个 prompt 写得不好”，而是：

`主模态规划层 -> PDF 工作层 -> 展示层 -> 状态层 -> Memory 层`

这五层边界没有被严格切开，系统处于一种“半隔离失败态”。

---

## 1.2 通过规划边界解决问题：先重画边界，再修局部能力

按照设计原则，PDF 不应被简单理解成“一个能返回文本的工具”。  
它在系统里应当被定义为：`由主模态调度、在专门工作域中执行、只向主线程回传稳定结果的阅读子域`。

也就是说，PDF 处理仍然受主模态统一调度，但必须把以下五层边界切清楚：

### A. 主模态规划层

职责：

- 识别用户任务是否属于 PDF 阅读
- 决定这是页级问题、章节问题，还是整文问题
- 管理用户意图、追问绑定、总任务目标

禁止：

- 直接消费 PDF raw snippet 作为主线程事实
- 把 PDF 中间态直接写进 main context

### B. PDF 工作层

职责：

- 负责页定位、章节定位、证据挑选、局部摘要、页质量判断
- 只产出结构化工作结果，不直接决定用户最终看到什么

禁止：

- 用中间态冒充正式摘要
- 把错误提示、降级说明、原始证据混装进 `summary`

### C. 展示收口层

职责：

- 只接收 canonical answer
- 决定“正式回答 / 安全降级 / 明确拒答”

禁止：

- 直接把 `tool_content`、evidence dump、诊断文本输出给用户

### D. 状态投影层

职责：

- 只在结果稳定时写入 `task_summary_refs`、`context_ref.summary`、`main_context`
- 为 follow-up 提供可续接的稳定状态

禁止：

- degraded/error 结果进入可续接状态
- 浏览型结果被误当成“已经完成阅读”

### E. Memory 投影层

职责：

- 只保存稳定、可复用、跨轮仍成立的阅读结论

禁止：

- 原始页片段、兜底摘要、临时定位结果、坏页判断直接进入 session memory

---

## 1.3 当前为什么会污染：不是完全未隔离，而是共享协议失控

当前系统不是完全没有隔离，而是形成了“执行隔离了一点，收口和持久化没隔离”的半成品状态。

具体表现为：

1. 任务识别层已经能把 PDF 识别成专门模态，并路由到 tool 执行链。
2. PDF 内部已经开始人为区分多种阅读路径和输出形态。
3. 但主线程仍然可以直接吃到 PDF raw content。
4. 分类器仍把非稳定 `summary` 当成可展示结果。
5. runtime 仍把降级结果投影回任务状态和记忆。

所以问题不是“有没有 PDF 专门链路”，而是：

- 有专门链路
- 但没有专门边界
- 有局部隔离
- 但没有显式共享协议

---

## 1.4 本次边界修复必须遵守的总原则

后续所有编码和重构，必须统一遵守以下边界原则：

1. 默认隔离，显式共享  
   PDF 工作层默认不能把任何文本直接暴露给主线程，只有显式标记为稳定结果的字段才能共享。

2. 单一收口源  
   用户可见答案只能来自 canonical answer，不能再出现 `tool_content` 和 canonical answer 双轨并存。

3. 中间态不入主线程  
   页候选、章节候选、整文候选、page evidence、错误诊断都属于工作态，不属于主线程事实。

4. 降级结果不持久化  
   degraded/error 结果可以短暂显示安全兜底，但不能进入 task summary、context summary、session memory。

5. 证据与摘要分离  
   evidence 是证据，summary 是稳定结论，两者必须是不同字段、不同语义、不同准入门。

6. 展示层与状态层分离  
   某轮可以“向用户安全降级”，但并不代表这轮结果可以成为后续追问的可续接基础。

7. 页码模型属于基础事实层  
   `document_total_pages`、`readable_pages`、`indexed_pages` 必须拆开；基础事实错了，上层阅读语义全部不可信。

8. 先治理边界，再优化摘要  
   在 direct tool 输出边界、canonical 协议、持久化门没修好前，不允许继续把精力主要放在 prompt 润色和摘要措辞上。

---

## 1.5 PDF 正式规则矩阵

这一版规则矩阵不再以“页文本打分后直接抽 top-k”作为主方案，而改成：

`解析 -> 结构分类 -> 候选集构造 -> 准入判定 -> canonical 收口 -> 状态投影`

这也是本次正式方案与之前临时修补方案的根本区别：

1. 先判定候选是否有资格进入正式答案，再讨论怎么总结。
2. 先做结构边界，再做排序。
3. 先做准入门，再做持久化门。

### 1.5.1 规则总纲

新的 PDF 正式规则必须满足四条总纲：

1. 结构优先  
   PDF 先被解析为结构单元，再进入阅读链；不能直接把整页纯文本当成正式语义单元。

2. 准入先于排序  
   排序只能在“允许进入候选集”的内容里发生；被排除类内容不能因为词命中高而反向进入正式答案。

3. 诊断与答案分离  
   可读、可索引、可定位，不等于可回答；诊断结果只能进入 diagnostic 通道，不能伪装成 stable summary。

4. 状态投影晚于准入  
   只有通过稳定准入门的结果，才允许进入 `task_summary_refs`、`context_ref.summary` 与 session memory。

### 1.5.2 解析层规则矩阵

解析层不再只输出“页文本”，而要为后续链路至少产出以下五类事实：

1. 文档事实
   - `document_total_pages`
   - `readable_pages`
   - `usable_pages`
   - `parse_strategy`
   - `parse_confidence`

2. 元素事实
   - `element_type`
   - `page_number`
   - `section_path`
   - `text`
   - `quality_flags`
   - `quality_score`

3. 页面事实
   - `page_exists`
   - `page_has_text`
   - `page_quality`
   - `page_excluded_ratio`

4. 结构事实
   - `section_heading`
   - `section_membership`
   - `reading_order`

5. 诊断事实
   - `ocr_noise`
   - `encoding_corruption`
   - `low_text_density`
   - `layout_missing`

解析策略本身采用成熟方案中的“策略选择”思路，不再默认一条链跑到底：

| 场景 | 正式策略 | 用途 | 备注 |
| --- | --- | --- | --- |
| 文本型 PDF，文本层可用 | `text_fast` | 优先取结构文本与页事实 | 类似 Unstructured `fast` 路径 |
| 版面重要、章节边界重要 | `layout_structured` | 提取 heading/body/furniture/table/image | 类似 Unstructured `hi_res` / Azure Layout / Docling body tree |
| 扫描件或文本层失真 | `ocr_recovery` | 做 OCR 恢复，但结果默认更严格 | 仅恢复文本，不自动放宽准入门 |
| 三者都失败 | `diagnostic_only` | 只产出诊断事实，不产出 stable summary | 不得伪装成可答文档 |

### 1.5.3 元素分类矩阵

正式链路里的元素分类如下：

| 元素类 | 示例 | 可做 evidence | 可做 stable summary | 可入记忆/摘要状态 | 规则说明 |
| --- | --- | --- | --- | --- | --- |
| `body_text` | 正文段落、论述段 | 是 | 是 | 是 | 主体答案只能来自这一类或其受控组合 |
| `section_heading` | 章节标题、小节标题 | 是 | 受限 | 受限 | 只能作为结构锚点，不能单独充当整文总结 |
| `table_text` | 表格正文、表头 | 受限 | 受限 | 受限 | 仅在问题明确问表格时可升级为稳定答案来源 |
| `figure_caption` | 图注、图片说明 | 受限 | 受限 | 受限 | 仅在问题明确问图/图示时进入稳定候选 |
| `header_footer` | 页眉页脚、重复页码 | 否 | 否 | 否 | 只保留为诊断或布局事实 |
| `toc_index` | 目录、索引 | 否 | 否 | 否 | 可辅助定位，禁止进入正式总结 |
| `references` | 参考文献、引文列表 | 受限 | 否 | 否 | 默认不进入整文/章节总结；只有“问参考文献”时可局部回答 |
| `cover_copyright` | 封面、版权、免责声明 | 否 | 否 | 否 | 只做元数据，不做答案 |
| `diagnostic_only` | 乱码、低质 OCR、断裂文本 | 否 | 否 | 否 | 只能触发降级或诊断 |

正式规定：

1. `document` 与 `section` 模式的稳定答案，默认只允许由 `body_text` 主导。
2. `references`、`toc_index`、`header_footer`、`diagnostic_only` 四类内容，默认属于 `excluded_from_summary`。
3. `table_text` 与 `figure_caption` 只有在用户问题明确指向这类对象时，才可升级为 `answer_eligible`。

### 1.5.4 候选集构造矩阵

在构造候选集时，不同问题类型有不同的允许来源：

| 问题类型 | 候选主来源 | 候选辅来源 | 明确排除 |
| --- | --- | --- | --- |
| `document_overview` | 多个 `body_text` 元素 | 对应 `section_heading` | `references`、`toc_index`、`header_footer`、`diagnostic_only` |
| `section_summary` | 同一 `section_path` 下的 `body_text` | 对应 heading | 纯 lexical top-k 页拼接 |
| `page_question` | 目标页上的 `body_text` | 同页 heading / table / caption | 仅凭“页存在且有字”即作答 |
| `reference_question` | `references` | 相邻 body/heading | 无 |
| `table_or_figure_question` | `table_text` / `figure_caption` | 相邻 body_text | 无 |

正式禁止：

1. 不能再用“整页排名 top-k”直接充当 `document_overview` 的候选集。
2. 不能再用“用户问全文总览 -> 直接合并三页文本”产出 stable summary。
3. 不能再用“章节没命中 -> 退化到普通页 lexical 排名”直接给 stable summary。

### 1.5.5 准入门矩阵

新的正式链路中，排序之后还必须经过准入门；不过门就只能降级，不能硬答。

为避免把阈值写死到文档里，计划书统一使用可配置门限符号：

- `T_page_quality_min`
- `T_body_chars_min`
- `T_doc_body_pages_min`
- `T_section_body_units_min`
- `R_excluded_max`

#### A. `document` 稳定摘要准入门

满足以下条件，才允许产出 `stable document summary`：

1. 候选集中至少覆盖 `T_doc_body_pages_min` 个不同正文页或正文结构单元。
2. 候选主内容以 `body_text` 为主，而不是尾页、目录页、参考文献页主导。
3. `excluded_from_summary` 内容占比不高于 `R_excluded_max`。
4. 至少存在一个清晰的章节锚点或正文连续性，而不是离散关键词拼页。

任一条件不满足：

- 返回 `degraded`
- 可以提供定位到的页码或结构事实
- 不能产出 stable summary

#### B. `section` 稳定摘要准入门

满足以下条件，才允许产出 `stable section summary`：

1. 成功定位到目标章节标题、章节路径，或至少两个同 section 的正文元素。
2. 候选正文长度达到 `T_body_chars_min`。
3. 候选集主要来自同一 section，而不是普通关键词命中页。
4. 章节候选中 `diagnostic_only` 与 `excluded_from_summary` 不占主导。

不满足时：

- 只能返回 `target_section_not_stably_located`
- 可以给候选 evidence
- 不能产出 stable section summary

#### C. `page` 稳定回答准入门

满足以下条件，才允许产出 `stable page answer`：

1. 目标页真实存在。
2. 该页通过 `T_page_quality_min`。
3. 该页正文可用字符达到 `T_body_chars_min`。
4. 页面不是以乱码、目录、参考文献、页眉页脚为主。

不满足时分两类：

1. 页存在但不可答
   - 返回 `degraded`
   - 原因是 `target_page_has_no_stable_text` 或 `target_page_text_quality_low`
2. 页不存在
   - 返回 `error`
   - 只报告事实页码，不猜测内容

### 1.5.6 状态投影矩阵

PDF 结果进入主系统时，必须按状态投影，而不是统一写回。

| 结果状态 | 可展示给用户 | 可写 `task_summary_refs` | 可写 `context_ref.summary` | 可入 session memory | 说明 |
| --- | --- | --- | --- | --- | --- |
| `stable` | 是 | 是 | 是 | 是 | 仅限通过正式准入门的稳定结果 |
| `degraded` | 是，但只能安全降级 | 否 | 否 | 否 | 可给页码、失败原因、最小诊断 |
| `error` | 是，但只能错误说明 | 否 | 否 | 否 | 错误事实可见，但不形成追问基础 |
| `diagnostic_only` | 受限 | 否 | 否 | 否 | 只能给运维/诊断信息，不给阅读结论 |

进一步约束：

1. `evidence` 可以随 `stable` 或 `degraded` 返回，但它永远不是 `summary`。
2. `degraded_reason` 与 `error` 只能留在 canonical 诊断字段中，不能冒充答案文本。
3. `task_summary_refs` 只能绑定稳定语义，不能绑定“这次读坏了但给了几个页码”的结果。

### 1.5.7 主线程共享矩阵

PDF 子域与主线程之间，只允许共享以下四类内容：

1. 稳定答案
   - `summary`
   - `pages`
   - `effective_mode`

2. 最小证据
   - 页码
   - 精简 snippet

3. 基础事实
   - `document_total_pages`
   - `readable_pages`
   - `usable_pages`

4. 失败原因
   - `degraded_reason`
   - `error`

明确不共享：

1. 原始整页文本
2. 中间候选排序明细
3. 低质量 OCR 片段
4. prompt 生成的兜底概括
5. tool 内部工作态标签

### 1.5.8 明确禁止的旧做法

以下做法在新的正式规则中被明确判定为违规实现：

1. 把 page lexical top-k 直接当成整文 summary 候选。
2. 把“可读页”直接等同于“可回答页”。
3. 把 reference/toc/copyright 页通过扣分后继续留在 stable summary 候选集里。
4. 把 degraded 结果通过 `summary` 字段回传。
5. 把 raw evidence 或 tool content 直接交给展示层和 memory 层。
6. 用更多正则和 penalty 堆出“看起来没那么差”的答案。

### 1.5.9 当前代码与正式规则的错位点

按这套矩阵回看当前代码，当前系统最大的错位点有四个：

1. `backend/pdf_analysis/parser.py`
   - 现在主要还是页文本抽取
   - 缺正式元素分类与结构树

2. `backend/pdf_agent/runtime.py`
   - 现在主要是页级排序
   - 缺准入门与 `excluded_from_summary` 候选边界

3. `backend/pdf_agent/models.py`
   - 现在 canonical 已拆出 `summary/degraded_reason/error`
   - 但还没有“元素事实 / 解析事实 / 诊断事实”的正式协议面

4. `backend/query/runtime.py`
   - 现在已经有一部分 PDF persistence gate
   - 但 gate 还是依赖 PDF 工具返回结果，而不是依赖一套正式准入规则对象

### 1.5.10 正式实施顺序

基于这套规则矩阵，后续修复顺序必须固定为：

1. 先补解析与元素分类协议
2. 再补候选集边界与准入门
3. 再补 canonical / state projection 协议
4. 最后再谈排序细化与摘要润色

否则就是继续拿“排序修补”去替代“结构修补”。

### 1.5.11 外部成熟方案对照来源

本规则矩阵不是凭经验拍出来的，主要借鉴了三类成熟做法：

1. Docling
   - 先把文档解析成 `DoclingDocument`
   - 再基于原生结构做 chunking，而不是先抹平成长文本再切

2. Unstructured
   - 先 `partition` 成结构元素，如 `Title`、`NarrativeText`、`ListItem`
   - 再在元素层做 `chunking`
   - PDF 解析策略按文档复杂度在 `fast / hi_res / ocr_only / auto` 之间选择

3. Azure AI Search Document Layout
   - 先做 layout 分析
   - 再输出 section-aware 的 markdown/text section
   - chunking 明确依附于 document layout，而不是脱离结构直接切页

因此，本项目新的 PDF 正式路线明确采用以下共识：

1. 先结构化，再候选化，再摘要化。
2. 先区分正文、结构锚点、排除类内容，再做检索和总结。
3. 先建立稳定准入门，再允许任何内容进入主线程与记忆层。

---

## 2. 本轮确认的坏点

## 2.1 P0: direct tool 最终显示边界失效

### 现象

长场景中多处出现：

- `answer_channel = fallback_answer`
- 但 `done.content` 仍然直接显示原始 PDF 脏片段、原始证据片段或错误文本

这说明系统虽然在分类层面已经知道“这不是稳定答案”，但展示层仍把脏内容发给用户。

### 根因

`backend/query/runtime.py` 中 direct tool 执行链存在边界错误：

- `render_content()` 已经算出了 canonical answer
- 但最终 `done.content` 仍直接使用 `tool_content`

结果是：

- 分类结果和用户可见内容分叉
- fallback 标记失去保护作用

### 风险

- 原始片段泄露到用户侧
- 脏结果继续进入 task summary
- session memory 被二次污染

---

## 2.2 P0: PDF canonical result 把中间态伪装成正式摘要

### 现象

这次“更坏”的关键不是旧字符串协议复活，而是新 canonical 协议本身定义过宽：

- 整文候选片段被塞进 `summary`
- 局部拼接片段被塞进 `summary`
- 章节兜底概括被塞进 `summary`
- 页面错误消息也被塞进 `summary`

之后 `output_classifier` 只要看见 `summary` 非空，就当成 tool-visible summary。

### 根因

当前 `PDFCanonicalResult.summary` 同时承担了三种完全不同的语义：

1. 真正稳定的用户摘要
2. 检索中间态
3. 错误或降级提示

这是协议层设计错误，不是调用层偶发错误。

### 风险

- canonical 协议丧失“收口”意义
- 下游无法判断何时可以进入主线程
- 后续 memory / follow-up 会把中间态当成正式结论

---

## 2.3 P0: 污染结果被写回任务状态与记忆

### 现象

脏结果不只出现在当前轮，还会出现在：

- `task_summary_refs`
- `context_ref.summary`
- `main_context`
- session memory projection
- 后续 PDF follow-up 的 hot truth

### 根因

当前 direct tool 执行完成后，会把结果直接投影为：

- task summary
- context ref summary
- main context state
- session-memory projection

而系统没有先判断这个结果是不是“稳定可保留”的 PDF 答案。

### 风险

- 当前轮脏，后续轮更脏
- follow-up 看起来“能续接”，实际上续的是污染结果
- 长场景越长，污染越重

---

## 2.4 P1: 页码模型不一致

### 现象

当前存在明显冲突：

- `pages = [72, 69, 71, 70]`
- 同时 `total_pages = 69`

还出现：

- `target page P4 does not exist`
- 但同一结果又写 `Detected page count is about 69`

### 根因

当前 `parser.extract_pages()` 只返回“抽出文本的页”，空文本页会被跳过。  
而 `PDFPreparedDocument.total_pages` 又用的是 `len(prepared_pages)`，不是 PDF 真实页数或最大页号。

因此：

- 一份真实有 72 页的 PDF，如果有 3 页没有抽出文本，就可能显示 `total_pages=69`
- 第 4 页如果抽取为空，就会被判定为“不存在”

### 风险

- 页追问逻辑失真
- 页级回答和章节回答的可信度直接被击穿
- 用户会感知为“系统连页码都对不上”

---

## 2.5 P1: 坏文本识别过弱

### 现象

页追问里仍然会出现：

- `隠㚵蔠裮䅳熱閔`
- 参考文献和 OCR 噪声混入页面要点

### 根因

当前 `looks_unusable_text()` 只做非常粗的长度和字符占比判断，无法识别：

- CJK 乱码
- 失配编码文本
- 低可读 OCR 噪声
- 文献页高密度引用串

### 风险

- 页面回答继续把坏页包装成“页面要点”
- 整文答案继续把脏页排进前列

---

## 2.6 P1: 人工模式化本身不是目标，但当前链路也没有可靠质量门

### 现象

当前链路试图把 PDF 问题拆成多种模式，但这些模式既没有形成稳定边界，也没有形成可靠质量门。

这意味着：

- 标签变多，不代表结果更稳
- 路由变细，不代表用户可见答案更可信
- 继续开发“精读 / 泛读”这类模式，只会扩大协议面和污染面

### 根因

当前系统在阅读任务上做了过早的模式化拆分，但没有同步建立：

- 稳定摘要门
- 降级输出门
- 证据质量门
- 可持久化门

所以问题不在于“模式还不够丰富”，而在于：

- 边界先没立住
- 结果准入先没立住
- 协议先没收紧

---

## 3. 为什么这次会比上次更坏

上次的问题主要是：

- PDF 答不出来
- 但大多数时候还能停在“安全 fallback 文案”

这次的问题变成：

- PDF 仍然答不稳
- 但 canonical 协议把中间态合法化了
- runtime 又把 direct tool 的 raw content 直接发给了用户

所以“更坏”的本质不是模型退化，而是：

1. 协议层误收口
2. 展示层边界失效
3. 记忆层继续扩散

---

## 4. 修复目标

本次修复不以“某一题回答更像样”作为完成标准，而以下列目标为准：

1. 不再把 PDF 原始中间态直接展示给用户
2. 不再把 PDF 中间态写入 task summary / session memory
3. 页码模型统一，`page`、`pages`、`total_pages` 不再互相打架
4. canonical result 只承载真正稳定的阅读结果
5. 不再把“精读 / 泛读”开发成正式模式体系，先收口成稳定单链路
6. 长场景测试把 PDF fallback 和页码错误纳入失败条件

---

## 5. 总体路线

## Phase A-0：先冻结旧模式入口

目标：

- 先把“精读 / 泛读 / 多模式分叉”从正式方案里降级为待删除残留
- 防止后续修边界时，旧模式逻辑继续扩散

策略：

1. 在文档和设计层面先取消旧模式的合法性
2. 对代码中的旧模式入口做清点、分组和删除顺序规划
3. 先停止新增任何基于 `browse / deep_read / section_read / page_read` 的新逻辑

完成标准：

- 计划书中明确旧模式不再属于正式目标
- 已有旧入口被纳入删除清单，不再被视为可继续演进的能力

---

## Phase A：止血

目标：

- 先阻止污染继续扩散

策略：

1. 修 direct tool 输出边界
2. 修 canonical 协议语义
3. 修 task summary / memory 投影门槛

完成标准：

- `done.content` 不再直接回填 `tool_content`
- PDF 降级结果不会再直接展示原始片段
- 脏 PDF 结果不会继续写入 `task_summary_refs`

---

## Phase B：校正

目标：

- 先把页码和文本基础数据做对

策略：

1. 统一真实页数与可读页数模型
2. 增强坏文本识别
3. 补齐参考文献页/目录页/版权页抑制

完成标准：

- 不再出现 `P4 不存在但 total_pages=69`
- 不再出现 `pages=72 但 total_pages=69`
- page_read 不再直接输出明显乱码页

---

## Phase C：重建

目标：

- 重新建立 PDF 阅读链的正式成功语义

策略：

1. browse 只做轻定位，不伪装成摘要
2. deep_read 才能产出文档级 summary
3. section_read 只在命中章节结构时给正式章节总结
4. page_read 只在页面文本质量通过时给用户答案

完成标准：

- “全文总览 / 核心结论 / 行动建议 / 第二部分约束 / 第N页内容”五类问题都有稳定行为

---

## 6. 分阶段修复清单

## 6.0 Phase A-0：旧模式残留冻结与清理计划

涉及范围：

- `backend/understanding/*`
- `backend/query/*`
- `backend/pdf_agent/*`
- `backend/tools/*`
- `backend/structured_memory/*`
- `backend/skills/pdf-analysis/*`
- `backend/SKILLS_REGISTRY.json`
- `backend/SKILLS_SNAPSHOT.md`
- `backend/TOOLS_REGISTRY.json`
- `backend/tests/*pdf*`

动作：

1. 冻结旧术语
   - 不再把 `browse / deep_read / section_read / page_read` 作为正式产品模式描述
   - 不再把“泛读 / 精读”写入技能说明、注册表、测试目标和设计文档
2. 盘点残留入口
   - 识别任务理解层的模式映射
   - 识别 query runtime 中的 `pdf_mode` 注入和追问续接逻辑
   - 识别 pdf agent runtime 中的多分支执行入口
   - 识别 skills、registry、snapshot、tool schema 中的旧描述
   - 识别 session memory / structured memory 中的模式投影字段
3. 分两步删除
   - 第一步：停用旧入口，只保留兼容映射，避免外部调用立即断裂
   - 第二步：在单链路收口稳定后，删除兼容映射、旧字段、旧测试名和旧文案
4. 建立清理约束
   - 不允许一边删除旧模式，一边继续新增新的模式分叉
   - 不允许把旧模式词换壳后继续存在于协议字段里

验收：

- 旧模式被明确降级为“待清理兼容残留”
- 后续修复工作不再以扩展旧模式为前提

---

## 6.1 Phase A-1：修 direct tool 输出边界

涉及文件：

- `backend/query/runtime.py`

动作：

1. `done.content` 改为输出 `tool_decision.canonical_answer`
2. `tool_end.output` 可以保留诊断值，但不可再当用户答案
3. `answer_channel=fallback_answer` 时，用户可见内容必须与 fallback 一致

验收：

- PDF 回合出现 fallback 时，用户只能看到安全 fallback 文案
- 不再出现“标记 fallback，但实际显示 raw content”

---

## 6.2 Phase A-2：收紧 PDF canonical 协议

涉及文件：

- `backend/pdf_agent/models.py`
- `backend/pdf_agent/runtime.py`
- `backend/query/output_classifier.py`

动作：

1. `PDFCanonicalResult.summary` 只允许表示“稳定用户摘要”
2. 新增或明确区分：
   - `summary`
   - `error`
   - `degraded_reason`
   - `evidence`
3. browse / section fallback / page error 不得再把兜底文本塞进 `summary`
4. `output_classifier` 只在 canonical result `ok` 时接受 `summary`

验收：

- browse 的“核心片段”不会再被主线程当正式答案
- page_read 错误不会再进入 `tool_visible_summary`

---

## 6.3 Phase A-3：加“可持久化门”

涉及文件：

- `backend/query/runtime.py`
- `backend/tasks/*`
- `backend/structured_memory/*`

动作：

1. PDF task summary 只在 canonical result 稳定时写入
2. 降级结果只保留最小诊断信息，不写 `summary.response`
3. `context_ref.summary` 不再盲写 `summary.response`
4. session memory projection 过滤掉 degraded/error PDF task

验收：

- follow-up 不再续接“脏摘要”
- session-memory 中不再出现原始 PDF 脏片段

---

## 6.4 Phase B-1：统一页码模型

涉及文件：

- `backend/pdf_analysis/parser.py`
- `backend/pdf_analysis/mineru_client.py`
- `backend/pdf_agent/runtime.py`

动作：

1. 区分：
   - `document_total_pages`
   - `readable_pages`
   - `indexed_pages`
2. `total_pages` 不再用 `len(prepared_pages)`
3. page_read 判断目标页是否存在时，应基于真实页号集合，而不是“抽出文本页列表”
4. 空文本页应保留页号占位，不能直接从文档页系里消失

验收：

- 页追问与总页数描述一致
- 页不存在报错只在真实越界时触发

---

## 6.5 Phase B-2：增强坏文本与坏页识别

涉及文件：

- `backend/pdf_analysis/parser.py`
- `backend/pdf_agent/runtime.py`

动作：

1. 识别编码异常文本
2. 识别低可读 OCR 噪声
3. 识别高密度引用串
4. 识别目录页、版权页、参考文献页
5. 对低质量页给出“不可稳定摘要”的统一降级，而不是直接输出页面要点

验收：

- `隠㚵蔠裮䅳熱閔` 类文本不再进入正式页面要点
- 文献页不再稳定排到整文答案前列

---

## 6.6 Phase B-3：重做 PDF 证据排序的质量前置

涉及文件：

- `backend/pdf_agent/runtime.py`

动作：

1. 排序前先做 quality gate
2. 将正文页、章节标题页与高质量内容页前置
3. 将参考文献页、稀疏页、目录页下压
4. 对总览/结论类问题，优先综合正文中段与结论段，不允许只靠词频命中

验收：

- “全文总览 / 核心结论 / 行动建议”不再稳定命中文献尾页

---

## 6.7 Phase C-1：取消“精读 / 泛读”模式化，重建单链路成功语义

涉及文件：

- `backend/pdf_agent/runtime.py`
- `backend/understanding/task_understanding.py`
- `backend/query/runtime.py`
- `backend/query/continuation_resolver.py`
- `backend/structured_memory/process_engine.py`
- `backend/structured_memory/session_memory_view.py`
- `backend/tools/pdf_analysis_tool.py`
- `backend/tools/definitions.py`
- `backend/skills/pdf-analysis/*`
- `backend/SKILLS_REGISTRY.json`
- `backend/SKILLS_SNAPSHOT.md`
- `backend/TOOLS_REGISTRY.json`
- PDF 相关 regression / artifacts

动作：

1. 删除“泛读 / 精读”作为正式产品能力的设计目标
2. PDF 阅读链收口成一条主链路：
   - 统一经过定位
   - 统一经过证据筛选
   - 统一经过质量门
   - 统一经过 canonical 收口
3. 页级问题和章节问题只保留为查询约束，不再包装成产品模式体系
4. 整文问题不再通过“泛读 / 精读”标签分叉，而是走同一主链路中的不同约束分支
5. 删除或改写旧残留：
   - 删除 `document_browse / document_deep_read` 这类 task kind
   - 删除 `pdf_mode=browse/deep_read/...` 这类对外暴露或持久化字段
   - 删除 skills、registry、snapshot 中关于“泛读 / 精读 / 模式标签”的描述
   - 重命名测试与产物，避免旧模式名继续成为回归基线
6. 对必须短期兼容的外部输入，只保留入口级归一化，不再向系统内部继续传播旧模式名

验收：

- 不再继续扩展“精读 / 泛读”模式面
- PDF 输出只剩一套稳定收口语义
- 旧模式名不再出现在正式设计、正式技能描述、正式状态投影和正式回归命名中

---

## 6.8 Phase C-2：收紧长场景验收

涉及文件：

- `backend/tests/system_eval/long_scenarios.py`
- `backend/tests/system_eval/long_runner.py`
- PDF 相关 regression

动作：

1. PDF 回合新增以下失败条件：
   - `answer_fallback_reason=pdf_missing_summary`
   - `response` 含明显 raw evidence 结构
   - 页码不一致
   - 页面不存在错误与总页数冲突
2. 补 PDF 专项指标：
   - stable_summary_rate
   - page_consistency_rate
   - followup_binding_integrity

验收：

- `3/3 passed` 不再掩盖 PDF 实质失效

---

## 7. 文件级实施顺序

第一批，必须先动：

1. `backend/understanding/task_understanding.py`
2. `backend/query/runtime.py`
3. `backend/query/output_classifier.py`
4. `backend/pdf_agent/runtime.py`
5. `backend/pdf_agent/models.py`

第二批，再动：

1. `backend/query/continuation_resolver.py`
2. `backend/structured_memory/process_engine.py`
3. `backend/structured_memory/session_memory_view.py`
4. `backend/tools/pdf_analysis_tool.py`
5. `backend/tools/definitions.py`
6. `backend/pdf_analysis/parser.py`
7. `backend/pdf_analysis/mineru_client.py`

第三批，再清：

1. `backend/skills/pdf-analysis/*`
2. `backend/SKILLS_REGISTRY.json`
3. `backend/SKILLS_SNAPSHOT.md`
4. `backend/TOOLS_REGISTRY.json`
5. PDF 相关 regression tests
6. 旧 artifacts / 旧命名产物

第四批，最后动：

1. `backend/tests/system_eval/long_runner.py`
2. `backend/tests/system_eval/long_scenarios.py`
3. 长场景基线与PDF专项回归

---

## 8. 每阶段必须复测

每完成一个阶段，都必须执行：

1. PDF direct-tool 回归
2. PDF follow-up 回归
3. core long scenario
4. 至少一轮包含 PDF 的长场景对照

且每次复测必须记录：

- 是否仍出现 raw content 外漏
- 是否仍出现 `pdf_missing_summary`
- 是否仍出现页码冲突
- 是否仍出现污染写回 session memory
- 是否仍出现旧模式名写回状态、记忆、测试报告或技能描述

---

## 9. 完成标准

本计划书的完成，不以“局部回答看起来更像样”为准，而必须同时满足：

1. PDF raw 中间态不再直接展示给用户
2. PDF degraded/error 结果不再写入可续接状态
3. 页码模型一致
4. canonical result 只承载稳定摘要
5. core long scenario 中 PDF 回合不再全部 fallback
6. 新增的长场景校验不会再把 PDF 失效误判为 passed
7. 旧模式残留不再出现在正式链路、正式文档、正式技能注册和正式测试命名中

---

## 10. 禁止事项

执行本修复时，明确禁止：

1. 继续用 fallback 文案掩盖 canonical 协议错误
2. 继续把 raw evidence 片段塞进 `summary`
3. 在 direct tool 链路里展示 `tool_content` 而不是 canonical answer
4. 继续用“抽到文本的页数”充当 `total_pages`
5. 在没有过滤的情况下把 PDF 结果写入 task summary 和 session memory
6. 继续把 `browse / deep_read / section_read / page_read` 当成正式产品模式扩展
7. 删除实现后却保留旧 registry、旧技能说明、旧测试命名，造成表面收口、实际残留

---

## 11. 最终目标

最终应得到的不是“PDF 勉强能答几题”，而是：

- PDF 阅读链有清晰的成功/失败语义
- 降级结果只会安全显示，不会污染系统
- follow-up 续接的是稳定阅读状态，而不是脏中间态
- 长场景报告能真实反映 PDF 是否健康

这份计划书是后续 PDF 修复的正式基线。  
后续编码应严格按“止血 -> 校正 -> 重建”的顺序推进，不得跳步直接做表层摘要优化。
