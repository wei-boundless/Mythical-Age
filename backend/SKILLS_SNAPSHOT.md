<skills>
  <summary>Available local workflow contracts. Skills constrain which task kinds they serve and which tools they may invoke.</summary>
  <skill name="天气查询" id="get-weather" path="skills/get-weather/SKILL.md">
    <description>查询指定地点的实时天气或短期天气情况，并整理成适合直接回复用户的中文结果。</description>
    <preferred_route>tool</preferred_route>
    <modalities>realtime</modalities>
    <source_kinds>external_web</source_kinds>
    <task_kinds>realtime_lookup</task_kinds>
    <allowed_tools>get_weather</allowed_tools>
    <capability_tags>weather, forecast, realtime</capability_tags>
    <routing_hints>天气, 气温, 温度, 预报, 下雨</routing_hints>
    <forbidden_routes>rag</forbidden_routes>
  </skill>
  <skill name="黄金价格查询" id="gold-price" path="skills/gold-price/SKILL.md">
    <description>使用专用黄金价格工具查询现货黄金或 XAU/USD 的实时价格，并返回整理后的中文结果与来源。</description>
    <preferred_route>tool</preferred_route>
    <modalities>realtime, finance</modalities>
    <source_kinds>external_web</source_kinds>
    <task_kinds>realtime_lookup</task_kinds>
    <allowed_tools>get_gold_price</allowed_tools>
    <capability_tags>gold, xau, realtime, finance, spot-price</capability_tags>
    <routing_hints>黄金, 金价, 现货黄金, XAU, XAUUSD, 实时黄金价格</routing_hints>
    <forbidden_routes>rag</forbidden_routes>
  </skill>
  <skill name="PDF 阅读分析" id="pdf-analysis" path="skills/pdf-analysis/SKILL.md">
    <description>用于本地 PDF 文件的泛读、精读和单页阅读，适合回答“这份 PDF 主要讲什么”“第几页讲什么”等问题。</description>
    <preferred_route>tool</preferred_route>
    <modalities>pdf, document</modalities>
    <source_kinds>document</source_kinds>
    <task_kinds>document_browse, document_deep_read, document_page_read</task_kinds>
    <allowed_tools>pdf_analysis</allowed_tools>
    <capability_tags>pdf, browse, deep-read, page-read</capability_tags>
    <routing_hints>白皮书, 报告, PDF, 第几页, 详细解读</routing_hints>
    <forbidden_routes>rag</forbidden_routes>
    <references>skills/pdf-analysis/references/pdf_reading.md</references>
  </skill>
  <skill name="知识库问答" id="rag-skill" path="skills/rag-skill/SKILL.md">
    <description>面向本地知识库目录的检索和问答能力，适合事实查询、FAQ 解释和基于本地文档的可追溯回答。</description>
    <preferred_route>rag</preferred_route>
    <modalities>text, document, knowledge</modalities>
    <source_kinds>knowledge_base</source_kinds>
    <task_kinds>knowledge_lookup, faq_explanation</task_kinds>
    <allowed_tools>search_knowledge</allowed_tools>
    <capability_tags>rag, retrieval, local-knowledge, faq</capability_tags>
    <routing_hints>知识库, 本地资料, 查资料, FAQ, 为什么</routing_hints>
    <forbidden_routes>tool</forbidden_routes>
  </skill>
  <skill name="重试经验沉淀" id="retry-lesson-capture" path="skills/retry-lesson-capture/SKILL.md">
    <description>当任务首轮失败、调整后成功时，提炼可复用经验，并写回当前 skill 或 durable memory。</description>
    <preferred_route>internal</preferred_route>
    <modalities>workflow</modalities>
    <source_kinds>workflow</source_kinds>
    <task_kinds>workflow_lesson_capture</task_kinds>
    <allowed_tools>read_file</allowed_tools>
    <capability_tags>lesson, retry, durable-memory</capability_tags>
    <routing_hints>失败后成功, 经验教训, 沉淀</routing_hints>
  </skill>
  <skill name="结构化数据分析" id="structured-data-analysis" path="skills/structured-data-analysis/SKILL.md">
    <description>用于本地 Excel、CSV、JSON 等结构化数据文件的通用分析场景，如统计、排序、分组汇总、Top N 和记录查询。</description>
    <preferred_route>tool</preferred_route>
    <modalities>table, spreadsheet, csv, json</modalities>
    <source_kinds>dataset</source_kinds>
    <task_kinds>dataset_schema_inspect, dataset_row_count, dataset_filter, dataset_summary, dataset_top_n, dataset_extreme_record, dataset_group_summary, dataset_inspect</task_kinds>
    <allowed_tools>structured_data_analysis</allowed_tools>
    <capability_tags>analytics, top-n, group-by, schema</capability_tags>
    <routing_hints>表格, Excel, CSV, 前五, 排名, 汇总</routing_hints>
    <forbidden_routes>rag</forbidden_routes>
    <references>skills/structured-data-analysis/references/excel_analysis.md, skills/structured-data-analysis/references/excel_reading.md</references>
  </skill>
  <skill name="联网搜索" id="web-search" path="skills/web-search/SKILL.md">
    <description>使用联网搜索获取最新信息、官方文档、新闻动态、实时行情和外部事实来源。</description>
    <preferred_route>tool</preferred_route>
    <modalities>realtime, web</modalities>
    <source_kinds>external_web</source_kinds>
    <task_kinds>web_lookup, realtime_lookup</task_kinds>
    <allowed_tools>web_search</allowed_tools>
    <capability_tags>search, news, finance, official-docs</capability_tags>
    <routing_hints>联网, 搜索, 最新, 新闻, 官网, 实时</routing_hints>
    <forbidden_routes>rag</forbidden_routes>
  </skill>
</skills>
