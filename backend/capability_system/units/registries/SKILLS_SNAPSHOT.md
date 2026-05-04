<skills>
  <summary>Skill registry snapshot for admin display. Runtime prompts should inject only the selected active skill.</summary>
  <skill name="PDF 阅读分析">
    <description>用于本地 PDF 文件的文档级、章节级和页级阅读分析，适合回答“这份 PDF 主要讲什么”“某一章讲什么”“第几页讲什么”等问题。</description>
    <use_when>Use for reading local documents or PDFs, including whole-document, section-level, and page-level questions.</use_when>
    <output_rule>Directly answer the user-facing task. Do not describe internal tool calls, routing policy, or protocol.</output_rule>
  </skill>
  <skill name="知识库问答">
    <description>面向本地知识库目录的检索和问答能力，适合事实查询、FAQ 解释和基于本地文档的可追溯回答。</description>
    <use_when>Use for local knowledge-base lookup, factual explanation, and questions that should be answered from local materials.</use_when>
    <output_rule>Directly answer the user-facing task. Do not describe internal tool calls, routing policy, or protocol.</output_rule>
  </skill>
  <skill name="结构化数据分析">
    <description>用于本地 Excel、CSV、JSON 等结构化数据文件的通用分析场景，如统计、排序、分组汇总、Top N 和记录查询。</description>
    <use_when>Use for structured data questions such as filtering, ranking, grouping, summary statistics, and record lookup.</use_when>
    <output_rule>Directly answer the user-facing task. Do not describe internal tool calls, routing policy, or protocol.</output_rule>
  </skill>
  <skill name="联网搜索">
    <description>使用联网搜索获取最新信息、官方文档、新闻动态、实时行情和外部事实来源。</description>
    <use_when>Use when the user needs current external information, real-time lookup, or official web sources.</use_when>
    <output_rule>Directly answer the user-facing task. Do not describe internal tool calls, routing policy, or protocol.</output_rule>
  </skill>
</skills>
