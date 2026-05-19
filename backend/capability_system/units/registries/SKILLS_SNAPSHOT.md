<skills>
  <summary>Skill registry snapshot for admin display. Runtime prompts should inject only the selected active skill.</summary>
  <skill name="PDF 阅读分析">
    <description>用于本地 PDF 的整篇阅读、章节定位和页级问答，适合回答“这份文档讲什么”“这一部分讲什么”“第几页写了什么”等深读问题。</description>
    <use_when>Use for reading local documents or PDFs, including whole-document, section-level, and page-level questions.</use_when>
    <delegation_protocol>When the main agent delegates, ask for pdf_reading; pass file path, page range or section, reading mode, and the exact question. If the user only needs knowledge-base evidence, return that the task belongs to rag-skill.</delegation_protocol>
    <return_protocol>Return a concise Chinese result with page or section anchors, a short summary, and any OCR or extraction limits. If the document is not enough, state exactly what is missing.</return_protocol>
    <output_rule>Directly answer the user-facing task. Do not describe internal tool calls, routing policy, or protocol.</output_rule>
  </skill>
  <skill name="知识库问答">
    <description>面向本地知识库、FAQ 和内部资料的检索问答工作流，适合做基于现有材料的事实确认、规则解释和可追溯回答。</description>
    <use_when>Use for local knowledge-base lookup, factual explanation, and questions that should be answered from local materials.</use_when>
    <delegation_protocol>When the main agent delegates, ask for evidence_lookup; pass the user question, the exact answer scope, known document anchors, and any active knowledge-base hints. If the question is about a PDF, dataset, or page/section, do not expand scope; return that this skill is not the right specialist.</delegation_protocol>
    <return_protocol>Return a concise Chinese result with three parts: conclusion, evidence, and limitations. Include the source name or retrieval anchor, the key fact fragments, and whether the evidence is sufficient. Do not mention internal tool names.</return_protocol>
    <output_rule>Directly answer the user-facing task. Do not describe internal tool calls, routing policy, or protocol.</output_rule>
  </skill>
  <skill name="Skill 创建顾问">
    <description>用于创建、改写和审查能力系统 Skill，帮助把用户意图整理成清晰的能力边界、触发条件、执行准则和模型可见提示。</description>
    <delegation_protocol>When the main agent delegates, ask for capability_design or skill_update; pass the target use case, expected trigger phrases, execution boundary, required tools, and whether the skill must coordinate with sub-agents. If the request is only a wording polish, keep scope narrow and avoid inventing new behavior.</delegation_protocol>
    <return_protocol>Return a concrete skill draft or review notes with three parts: boundary, prompt structure, and validation gaps. Clearly separate what should be changed in metadata, what should be changed in the body, and what should remain untouched. If the skill is too broad, say how to split it.</return_protocol>
    <output_rule>Directly answer the user-facing task. Do not describe internal tool calls, routing policy, or protocol.</output_rule>
  </skill>
  <skill name="结构化数据分析">
    <description>用于本地 Excel、CSV、JSON 等结构化数据的可计算分析，适合筛选、排序、分组汇总、Top N、极值记录和结构检查。</description>
    <use_when>Use for structured data questions such as filtering, ranking, grouping, summary statistics, and record lookup.</use_when>
    <delegation_protocol>When the main agent delegates, ask for table_analysis; pass dataset path, required columns, filter or grouping rules, ranking criteria, and the required output shape.</delegation_protocol>
    <return_protocol>Return the computed answer, the calculation basis, and the relevant rows or aggregates. If the data is incomplete, state which column or sheet is missing.</return_protocol>
    <output_rule>Directly answer the user-facing task. Do not describe internal tool calls, routing policy, or protocol.</output_rule>
  </skill>
</skills>
