<skills>
  <summary>Skill registry snapshot for admin display. Runtime prompts should inject only the selected active skill.</summary>
  <skill name="网页操作">
    <description>让主 Agent 使用受控浏览器打开网页、观察页面、点击、输入、等待、截图和抽取内容。</description>
    <use_when>用户要求打开网页、搜索问题、点击页面、填写表单、检查前端页面、截图验证、从网页抽取内容时使用。

不适合用于纯 HTTP 抓取；如果只需要读取一个静态 URL，优先使用 `fetch_url`。</use_when>
    <return_protocol>向用户汇报时只说已完成什么、看到什么、下一步需要什么。不要暴露内部 selector 细节，除非用户在调试页面。</return_protocol>
    <output_rule>向用户汇报时只说已完成什么、看到什么、下一步需要什么。不要暴露内部 selector 细节，除非用户在调试页面。</output_rule>
  </skill>
  <skill name="深度网络研究">
    <description>用于跨来源深度网络研究，要求建立研究合同、分面搜索、阅读关键原文、交叉验证证据，并输出可信度、限制和可追溯来源。</description>
    <use_when>用户需要系统调研、技术路线比较、GitHub/论文/官方资料综合、竞品分析、证据交叉验证或高可信结论；问题不能只靠一次搜索摘要可靠回答。</use_when>
    <delegation_protocol>先建立研究合同和搜索面；用 web_search 扩展候选来源，用 fetch_url 阅读关键原文；范围较大且允许子 agent 时，可按论文、GitHub、官方资料、新闻公告分派子任务并等待结构化结果。</delegation_protocol>
    <return_protocol>返回研究结论、证据表、来源质量判断、冲突点、可信度、限制和建议下一步；关键结论必须能追溯到来源。</return_protocol>
    <output_rule>先给结论和判断，再列证据；不要暴露内部工具名、路由名、skill_id 或未整理的搜索日志。</output_rule>
  </skill>
  <skill name="生图提示词设计">
    <description>用于角色立绘、场景图、封面图和视觉参考图生成。主 Agent 应在用户明确要求出图时，用它把意图整理成可执行的高质量提示词，并调用生图工具产出真实图片。</description>
    <return_protocol>- 调用成功后，返回真实图片结果，不要只返回 prompt。
- 调用失败时，说明失败原因，并保留用户原需求与整理后的 prompt，方便重试。</return_protocol>
    <output_rule>- 调用成功后，返回真实图片结果，不要只返回 prompt。
- 调用失败时，说明失败原因，并保留用户原需求与整理后的 prompt，方便重试。</output_rule>
  </skill>
  <skill name="PDF 阅读分析">
    <description>用于本地 PDF 的整篇阅读、章节定位和页级问答，适合回答“这份文档讲什么”“这一部分讲什么”“第几页写了什么”等深读问题。</description>
    <use_when>- 用户点名某个 PDF、报告、白皮书、手册、论文。
- 用户问“第几页讲了什么”“第二部分强调了什么”“这份文档核心观点是什么”。
- 会话里已经有激活的 PDF 绑定，用户继续追问“这一页”“这一部分”“这份 PDF”。</use_when>
    <delegation_protocol>当主 Agent 委派给你时，应明确说明：

- `delegation_kind=pdf_reading`
- 目标文件路径或文件句柄
- 页码、章节、全文、摘要中的哪一种阅读粒度
- 用户真正想要的产出形式
- 是否允许跨页归纳，还是只允许局部阅读

主 Agent 应尽量把问题写成“请阅读什么、关注什么、输出什么”，例如：



主 Agent 传入的 `input_payload` 应尽量包含：

- `query`：当前用户真正问的问题，不要只写“继续看”。
- `path` 或 `active_pdf`：目标 PDF 路径或句柄。
- `mode`：`page`、`section` 或 `document`。
- `page` / `pages` / `section`：如果用户限定了页码或章节，要显式传入。
- `followup_constraint_policy`：如果是续接任务，要说明是否禁止切换文档或扩大范围。
- `expected_output_contract`：要求回传 `summary`、`answer_candidate`、`evidence_refs`、`limitations` 和 `confidence`。

如果主 Agent 给你的输入里同时出现 PDF 与表格/数据集约束，你应优先检查当前任务是不是被错派。只要核心问题是“按部门/前五/全表/汇总/统计”，就应在限制中提示应改派 `structured-data-analysis`，不要把数据问题硬读成 PDF 问题。</delegation_protocol>
    <return_protocol>你返回给主 Agent 的结果应包括：

- `summary`：对当前问题的直接回答
- `evidence_refs`：页码、章节或文档锚点
- `artifact_refs`：如有 OCR 产物或分析产物，提供引用
- `limitations`：抽取噪声、页码缺失、图表难读等限制
- `followup_questions`：只有在必须补读时才提出
- `consumed_handles`：你实际阅读的 PDF、页码、章节或结果句柄
- `produced_handles`：可复用的阅读结果或摘读产物句柄

你应始终把页码、章节或文档锚点写清楚，让主 Agent 能直接收口。</return_protocol>
    <output_rule>- 页级问题优先保留定位感，说明是基于哪一页或哪一部分。
- 总览问题优先给摘要，再给重要章节或结论。
- 有明显 OCR 噪声或抽取不完整时，要提示不确定性。
- 遇到图表、附录、脚注等边缘内容，不要把局部细节误讲成全文中心。
- 组织结果时优先用“结论 / 页码或章节 / 关键内容 / 限制”四段式。
- 如果用户要行动建议，要把建议和文档原意分开写，避免把建议伪装成原文结论。
- 如果是一页只够支撑局部判断，就明确说这是局部判断，不要冒充全文结论。</output_rule>
  </skill>
  <skill name="知识库问答">
    <description>面向本地知识库、FAQ 和内部资料的检索问答工作流，适合做基于现有材料的事实确认、规则解释和可追溯回答。</description>
    <use_when>- 用户明确提到知识库、本地资料、内部文档、FAQ、帮助中心、规则说明。
- 问题本质上是在确认一个事实、解释一个规则、核对一个产品能力、说明一个常见故障原因。
- 回答需要“根据现有材料来讲”，而不是依赖最新外部信息或临时计算。</use_when>
    <delegation_protocol>当主 Agent 需要你执行检索时，应把任务写成“可直接执行”的委派说明，而不是笼统地说“查一下”。

主 Agent 应传入：

- `delegation_kind=evidence_lookup`
- 用户原问题
- 期望回答范围
- 已知知识库锚点或文档线索
- 若有，当前绑定的资料名、主题词、路径线索或 follow-up 约束
- `expected_output_contract`：要求回传 `summary`、`answer_candidate`、`evidence_refs`、`limitations` 和 `confidence`

适合的主 Agent 指令风格：



如果用户的问题其实是 PDF 页级阅读、表格统计或最新外部信息，你应明确回传“这不是知识库检索的最佳入口”，并提示主 Agent 改派对应技能。</delegation_protocol>
    <return_protocol>你返回给主 Agent 的结果应保持稳定结构：

- `summary`：一句话结论
- `evidence_refs`：可引用的证据线索
- `artifact_refs`：如有，可回传产物引用
- `limitations`：证据不足、覆盖范围有限、索引不全等限制
- `followup_questions`：只有在必须补充上下文时才提出
- `consumed_handles`：你实际使用的知识库、文档或检索锚点
- `produced_handles`：如生成了可复用结果，回传结果句柄

回传内容应满足：

- 先结论，后证据
- 证据不足就直接说不足，不要编造补全
- 不暴露内部工具名、路由名、协议名
- 如果只能给出近似判断，要明确标注不确定性
- 如果判断出任务不属于知识库检索，应在 `limitations` 中写明推荐的能力域，例如 `requires_pdf_reading` 或 `requires_structured_data_analysis`</return_protocol>
    <output_rule>- 结论优先，不要先铺陈检索过程。
- 尽量保留来源感，比如“根据知识库说明”或“从现有资料看”。
- 有冲突证据时，不要强行合并，要说明冲突点。
- 没有足够依据时，不要补齐想象内容。
- 组织结果时优先用“结论 / 依据 / 限制 / 下一步”四段式。
- 如果能给业务语言翻译，就把术语翻译成业务能懂的话，但不要丢掉证据锚点。
- 如果证据分散，先合并成一个清楚判断，再列出最关键的两三条证据，不要堆片段。</output_rule>
  </skill>
  <skill name="Skill 创建顾问">
    <description>用于创建、改写和审查能力系统 Skill，帮助把用户意图整理成清晰的能力边界、触发条件、执行准则和模型可见提示。</description>
    <use_when>当用户要新增、改写、审查或拆分 Skill 时使用；重点处理能力边界、触发条件、依赖 operation、正文是否面向 Agent 执行、以及输出协议是否稳定。</use_when>
    <return_protocol>返回 Skill 草案或审查意见时，分清 metadata、prompt/body、requires_operations、requires_capabilities、适用场景、不适用场景、验证缺口；如果能力过宽，直接给出拆分建议。</return_protocol>
    <output_rule>先给可执行结论，再给需要修改的具体字段和正文片段；不要把 Skill 写成开发说明，不要编造不存在的工具或权限。</output_rule>
  </skill>
  <skill name="结构化数据分析">
    <description>用于本地 Excel、CSV、JSON 等结构化数据的可计算分析，适合筛选、排序、分组汇总、Top N、极值记录和结构检查。</description>
    <use_when>- 用户提到 Excel、CSV、JSON、表格、数据库导出、库存表、订单表、员工表。
- 用户问的是“前五 / 最高 / 最低 / 按地区汇总 / 哪些符合条件 / 一共有多少 / 某类记录有哪些”。
- 会话里已经绑定了一个数据集，用户继续追问“按仓库展开一下”“把前五列出来”“再按地区看一下”。</use_when>
    <delegation_protocol>当主 Agent 委派给你时，应明确传入：

- `delegation_kind=table_analysis`
- `query`：当前用户真正要求的计算或汇总问题
- `path` 或 `active_dataset`：目标数据集路径或句柄
- 筛选、分组、排序、Top N、字段口径等约束
- 如果是 follow-up，传入 `active_result_handle_id`、`active_subset_handle_id`、`followup_target_refs`
- 如果用户说“这些人 / 这前五名 / 不要扩展回全表”，必须传入 `followup_constraint_policy=result_subset_only_do_not_expand_to_full_object`
- `expected_output_contract`：要求回传 `summary`、`answer_candidate`、`evidence_refs`、`limitations`、`confidence`

适合的主 Agent 指令风格：



如果主 Agent 给你的输入里同时出现 PDF、报告页码或知识库检索要求，你应先判断是否被错派。核心问题是文档页级阅读时，应提示改派 `pdf-analysis`；核心问题是资料事实确认时，应提示改派 `rag-skill`。</delegation_protocol>
    <return_protocol>你返回给主 Agent 的结果应包括：

- `summary`：一句话说明计算结论。
- `answer_candidate`：可直接收口的中文答案草稿。
- `evidence_refs`：相关行、聚合结果、字段或结果句柄。
- `limitations`：字段缺失、口径不明、数据不完整、只能基于子集等限制。
- `consumed_handles`：实际使用的数据集、结果子集或结果句柄。
- `produced_handles`：新生成的分析结果、聚合表或摘要句柄。</return_protocol>
    <output_rule>- 先给结果，再补充筛选条件、分组逻辑或关键数字。
- 如果问题有歧义，要指出歧义点，例如时间范围、字段口径、排序依据。
- 对 Top N、极值、汇总类问题，尽量让结果可比、可核对。
- 如果数据不完整、字段不明确或绑定数据集不对，要明确说明。
- 组织结果时优先用“结论 / 口径 / 结果表 / 注意事项”四段式。
- 如果字段名不直观，要把计算口径翻译成业务语言再给出。
- 如果用户只要一个答案，就别把完整表格铺满；保留最相关的几项和可核对的口径即可。</output_rule>
  </skill>
  <skill name="视觉资产生成">
    <description>在任务合同或用户请求需要真实图片交付物时，指导 agent 调用 image_generate 生成可验收的视觉资产，并把工具返回的真实路径作为交付证据。</description>
    <output_rule>直接完成用户可见任务；不要描述内部工具调用、路由策略或协议。</output_rule>
  </skill>
  <skill name="快速网络简报">
    <description>用于快速搜索当前网络信息并给出简短、有来源链接的简报，适合新闻、官网状态、当前事实和轻量资料确认。</description>
    <use_when>用户需要快速了解当前网络信息、最近新闻、官网状态、发布动态或少量来源链接；任务目标明确，通常不需要跨来源深度论证。</use_when>
    <delegation_protocol>先用 web_search 获取候选来源；只有关键日期、版本、声明或结论需要确认时才使用 fetch_url 阅读原文；不要启动长任务，除非用户明确要求持续研究或产出文件。</delegation_protocol>
    <return_protocol>返回结论、来源链接、日期或更新时间、简短影响说明和无法确认的限制；链接必须来自实际搜索或抓取结果。</return_protocol>
    <output_rule>简短直接，先给结果；不要暴露内部工具名、路由名、skill_id 或搜索过程日志。</output_rule>
  </skill>
</skills>
