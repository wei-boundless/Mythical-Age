<skills>
  <summary>Skill registry snapshot for admin display. Runtime prompts should inject only the selected active skill.</summary>
  <skill name="PDF 阅读分析">
    <description>用于本地 PDF 的整篇阅读、章节定位和页级问答，适合回答“这份文档讲什么”“这一部分讲什么”“第几页写了什么”等深读问题。</description>
    <use_when>Use for reading local documents or PDFs, including whole-document, section-level, and page-level questions.</use_when>
    <output_rule>Directly answer the user-facing task. Do not describe internal tool calls, routing policy, or protocol.</output_rule>
  </skill>
  <skill name="知识库问答">
    <description>面向本地知识库、FAQ 和内部资料的检索问答工作流，适合做基于现有材料的事实确认、规则解释和可追溯回答。</description>
    <use_when>Use for local knowledge-base lookup, factual explanation, and questions that should be answered from local materials.</use_when>
    <output_rule>Directly answer the user-facing task. Do not describe internal tool calls, routing policy, or protocol.</output_rule>
  </skill>
  <skill name="结构化数据分析">
    <description>用于本地 Excel、CSV、JSON 等结构化数据的可计算分析，适合筛选、排序、分组汇总、Top N、极值记录和结构检查。</description>
    <use_when>Use for structured data questions such as filtering, ranking, grouping, summary statistics, and record lookup.</use_when>
    <output_rule>Directly answer the user-facing task. Do not describe internal tool calls, routing policy, or protocol.</output_rule>
  </skill>
</skills>
