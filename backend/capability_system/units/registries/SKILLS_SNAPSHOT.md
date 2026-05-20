<skills>
  <summary>Skill registry snapshot for admin display. Runtime prompts should inject only the selected active skill.</summary>
  <skill name="PDF 阅读分析">
    <description>用于本地 PDF 的整篇阅读、章节定位和页级问答，适合回答“这份文档讲什么”“这一部分讲什么”“第几页写了什么”等深读问题。</description>
    <use_when>Use for reading local documents or PDFs, including whole-document, section-level, and page-level questions.</use_when>
    <delegation_protocol>When the main agent delegates, ask for pdf_reading; pass query, path/active_pdf, page or section mode, follow-up constraints, and expected_output_contract. Return page/section anchors and extraction limits; if the task is knowledge-base lookup or data aggregation, report the better specialist.</delegation_protocol>
    <return_protocol>Return summary, answer_candidate, page or section evidence_refs, artifact_refs if any, confidence, limitations, consumed_handles, and produced_handles. State OCR/extraction limits explicitly.</return_protocol>
    <output_rule>Directly answer the user-facing task. Do not describe internal tool calls, routing policy, or protocol.</output_rule>
  </skill>
  <skill name="知识库问答">
    <description>面向本地知识库、FAQ 和内部资料的检索问答工作流，适合做基于现有材料的事实确认、规则解释和可追溯回答。</description>
    <use_when>Use for local knowledge-base lookup, factual explanation, and questions that should be answered from local materials.</use_when>
    <delegation_protocol>When the main agent delegates, ask for evidence_lookup; pass query, exact answer scope, known knowledge-base anchors, follow-up constraints, and expected_output_contract. If the task is actually PDF reading, dataset analysis, or current web research, return a limitation naming the better specialist instead of expanding scope.</delegation_protocol>
    <return_protocol>Return summary, answer_candidate, evidence_refs, artifact_refs if any, confidence, limitations, consumed_handles, and produced_handles. Use conclusion/evidence/limitations wording and do not mention internal tool names.</return_protocol>
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
    <delegation_protocol>When the main agent delegates, ask for table_analysis; pass query, path/active_dataset, required columns, filter/grouping/ranking criteria, active result/subset handles, follow-up constraint policy, and expected_output_contract.</delegation_protocol>
    <return_protocol>Return summary, answer_candidate, calculation evidence_refs, artifact_refs if any, confidence, limitations, consumed_handles, and produced_handles. State field, sheet, or subset limits explicitly.</return_protocol>
    <output_rule>Directly answer the user-facing task. Do not describe internal tool calls, routing policy, or protocol.</output_rule>
  </skill>
</skills>
