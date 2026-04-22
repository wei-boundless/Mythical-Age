# Docling 与 LlamaIndex 版前处理和 RAG 重建计划书

> 编写日期：2026-04-21
> 目标：将当前“自写前处理 + 自写索引生命周期 + 自写 hybrid 检索”的 RAG 底层，重建为“结构化文档转换层 + 标准化 ingestion/index/retrieval 内核”，同时保留现有主线程控制、显式句柄续接、输出收口原则。

---

## Part A. 技术报告

## 1. 问题定义

当前系统的 RAG 问题，不是单点召回参数没调好，而是底层三层都存在结构性缺陷：

1. 前处理层仍以“抽文本”为主，而不是“抽结构”。
2. 索引层既负责解析、切块、建索引、缓存、BM25，又负责加载和检索，职责过重。
3. 检索层 steady-state 不稳定，dense miss 后会掉进高成本全量解析路径。

这导致三类直接后果：

- 文档结构在进入索引前就已经损失，尤其是 PDF、表格、图片、页内关系。
- 持久化后端和运行时后端容易错配，出现“有索引但检不出来”。
- 检索 miss 会转化成严重延迟，最终还会把坏输出推入主链。

本次重建的真实目标不是“把库换成 LlamaIndex”，而是：

> 用更强的结构化文档转换层重建前处理，用标准化 ingestion/index/retrieval 重建检索内核，并保持主线程继续由本项目 runtime 明确掌控。

---

## 2. 当前系统现状

## 2.1 当前前处理结构

当前知识库文档的主要入口仍是：

- [parser_adapter.py](/D:/AI应用/langchain-agent/backend/RAG/parser_adapter.py)
- [parser.py](/D:/AI应用/langchain-agent/backend/pdf_analysis/parser.py)
- [cleaner.py](/D:/AI应用/langchain-agent/backend/RAG/cleaner.py)

现状特征：

- `MultimodalParserAdapter` 按文件后缀分发解析。
- `PdfTextParser` 以页文本抽取为核心，远端 MinerU 只是增强分支。
- `ParsedContentCleaner` 主要靠启发式去重、去页眉、去噪。
- 输出协议只有 `ParsedChunk(text/source/modality/page/section/metadata)`。

这套协议过薄，无法稳定表达：

- 阅读顺序
- block 层级
- 标题树
- 表格和 caption 关系
- 图像与页内上下文
- 同一文档内块与块之间的引用关系
- 结构对象级句柄

## 2.2 当前索引与检索结构

当前核心模块：

- [registry.py](/D:/AI应用/langchain-agent/backend/RAG/registry.py)
- [router.py](/D:/AI应用/langchain-agent/backend/RAG/router.py)
- [service.py](/D:/AI应用/langchain-agent/backend/retrieval/service.py)
- [collections.py](/D:/AI应用/langchain-agent/backend/RAG/collections.py)
- [hybrid.py](/D:/AI应用/langchain-agent/backend/RAG/hybrid.py)

当前问题：

- `CollectionIndexer` 同时承担文档收集、解析、切块、建索引、加载、BM25、hybrid 检索。
- `vector_store_backend` 历史上允许配置值与实际支持值不一致，容易静默回退。
- `_ensure_documents_cache()` 依赖全量重建文档缓存，steady-state 成本高。
- 自写 BM25 与自写 fusion 增强了可控性，但也把生命周期复杂度拉高。

## 2.3 当前对上层系统的影响

RAG 底层问题已经影响到主线程语义质量：

- 首问检不出来时，答案层会更容易接到协议残留或占位输出。
- 检索和摘要不稳定时，follow-up 会承接坏结果而不是承接真实对象。
- PDF 和结构化数据问答常退化成“定位成功但无法总结”。

这说明本次重建不能只改索引后端，必须连前处理一起重建。

---

## 3. 本项目的设计约束

本次重建必须服从已有主线程原则，不能为了换底层框架把控制权重新交回黑盒。

结合 [38-去启发式续接与显式句柄主链重构技术报告及计划书.md](/D:/AI应用/langchain-agent/docs/38-去启发式续接与显式句柄主链重构技术报告及计划书.md) 以及相关架构文档，可以提炼出 5 条硬约束：

1. 恢复不等于裁决。
2. 默认隔离，显式共享。
3. 主线程保留控制面真相，检索层只返回证据，不参与主链裁决。
4. 显式句柄优先于弱语言线索。
5. 输出层只能消费被规范化后的检索结果和总结结果，不能直接消费原始协议残留。

由此得到一个关键结论：

> 可以把文档转换、切块、索引、检索交给更成熟的框架，但不能把 follow-up、binding、main-context、canonical answer 一起交出去。

---

## 4. 外部方案对比与采用结论

## 4.1 Docling

官方资料显示，Docling 的核心能力是把 PDF、DOCX、PPTX、图片等文档转成统一且结构化的 `DoclingDocument`，并保留元数据、结构关系、表格、OCR、阅读顺序等信息。

来源：

- https://www.docling.ai/
- https://docling.site/features/
- https://docling-project.github.io/docling/reference/document_converter/
- https://docling-project.github.io/docling/concepts/docling_document/

适配性判断：

- 非常适合替换当前 `parser_adapter + pdf_parser + cleaner` 主链。
- 适合作为统一文档转换层，而不是临时 PDF 工具。
- 能为后续对象级索引提供更厚的数据基础。

## 4.2 LlamaIndex

官方资料显示，LlamaIndex 在 ingestion pipeline、transformations、持久化索引、BM25、fusion retrieval 上都已具备成熟能力。

来源：

- https://docs.llamaindex.ai/en/stable/module_guides/loading/ingestion_pipeline/
- https://docs.llamaindex.ai/en/stable/module_guides/indexing/vector_store_index/
- https://docs.llamaindex.ai/en/stable/module_guides/storing/save_load/
- https://docs.llamaindex.ai/en/latest/api_reference/retrievers/bm25/
- https://docs.llamaindex.ai/en/stable/api_reference/retrievers/query_fusion/

适配性判断：

- 非常适合接管 ingestion/index/retrieval 内核。
- 适合接管 dense、BM25、fusion 和持久化生命周期。
- 不适合直接接管本项目的 follow-up / binding / main thread truth。

## 4.3 最终采用路线

本项目推荐采用：

> Docling 负责统一结构化文档转换
> LlamaIndex 负责 ingestion/index/retrieval
> 本项目原有 runtime 继续负责主线程控制、显式续接、输出收口

不采用的路线：

- 不做“继续修自写 parser_adapter”的小修路线。
- 不做“让 LlamaIndex query engine 直接主导答案生成”的大包大揽路线。
- 不做“仅换向量后端，不重做前处理”的半重建路线。

---

## 5. 目标架构

## 5.1 分层结构

目标分为 4 层：

### A. Document Conversion Layer

职责：

- 读取原始文档
- 转换为统一结构化中间表示
- 输出文档级、块级、对象级信息

建议主引擎：

- Docling

### B. Normalized Ingestion Layer

职责：

- 将外部转换结果规范化为本项目内部唯一 ingestion 协议
- 做结构块、对象块、页块、摘要块的标准化生成
- 进行缓存、去重、版本化

### C. Retrieval Core Layer

职责：

- 持久化索引
- dense retriever
- lexical retriever
- fusion retriever
- collection-level retrieval

建议主引擎：

- LlamaIndex

### D. Orchestration Layer

职责：

- 任务理解
- route 选择
- follow-up 句柄续接
- binding 归属判断
- canonical answer 产出

继续保留本项目现有主线程结构。

## 5.2 关键边界

新的边界定义：

- 文档转换层不决定“用户当前问的是谁”。
- 检索层不决定“当前轮应该继续哪个对象”。
- 主线程不直接读取原始文档，只消费规范化后的检索结果。
- 输出层不直接消费 raw parser output，只消费已经归一化的 retrieval hit 或上层总结结果。

## 5.3 端到端执行流程

为避免实施时再次出现“边改边决定”的漂移，本次先把目标主链固定为如下 9 步：

1. `source file discovery`
2. `document conversion`
3. `normalized document build`
4. `block/object/page-summary generation`
5. `ingestion cache persist`
6. `dense/lexical index build`
7. `query-mode aware retrieval`
8. `retrieval hit normalization`
9. `runtime consumption and answer assembly`

对应的固定责任边界如下：

### Step 1. Source File Discovery

输入：

- `CollectionConfig`
- `source_dirs`
- `allowed_roots`

输出：

- `SourceFileRecord[]`

固定约束：

- 只负责发现文件，不做解析
- 只产生稳定 `source_path` 与 `version_digest`

### Step 2. Document Conversion

输入：

- `SourceFileRecord`

输出：

- `ConversionResult`

固定约束：

- 主转换器为 Docling
- 旧 parser 只能作为 fallback
- 这里不做 retrieval-oriented chunking

### Step 3. Normalized Document Build

输入：

- `ConversionResult`

输出：

- `NormalizedDocument`
- `NormalizedBlock[]`
- `NormalizedObjectRef[]`

固定约束：

- 这是项目内部唯一标准协议
- LlamaIndex 不直接读取原始文件

### Step 4. Block/Object/Page-Summary Generation

输入：

- `NormalizedDocument`
- `NormalizedBlock[]`
- `NormalizedObjectRef[]`

输出：

- `IndexableUnit[]`

固定约束：

- 结构块与对象块分离
- 页摘要块是独立视图，不与正文混成同一块
- 只有通过结构化清洗和可索引性判定的 block 才能进入主索引
- `<!-- image -->`、`<!-- table -->`、纯装饰标题、超短噪声块不能直接进入主 dense 索引
- 页摘要只能基于“可索引正文块”生成，不能基于占位块或 OCR 噪声生成

### Step 5. Ingestion Cache Persist

输入：

- `IndexableUnit[]`

输出：

- `conversion_manifest.json`
- `normalized_manifest.json`
- `ingestion_cache/`

固定约束：

- 新旧链路分别存储
- steady-state 查询不允许重新解析原文

### Step 6. Dense/Lexical Index Build

输入：

- `IndexableUnit[]`

输出：

- dense index
- lexical index
- index metadata

固定约束：

- 新索引必须写入 `indexes_v2`
- 配置、元数据、磁盘产物三者必须一致

### Step 7. Query-Mode Aware Retrieval

输入：

- `query`
- `query_mode`
- `selected_collections`

输出：

- dense hits
- lexical hits
- fused hits

固定约束：

- query mode 由主线程决定
- 检索内核不自行推断“当前到底要继续谁”

### Step 8. Retrieval Hit Normalization

输入：

- raw retriever outputs

输出：

- `RetrievalHit[]`

固定约束：

- 所有 hits 都要带 `doc_id/block_id/block_type`
- 不能再向上暴露“只有 text 和 score 的薄对象”

### Step 9. Runtime Consumption and Answer Assembly

输入：

- `RetrievalHit[]`
- `main_context`
- `followup_resolution`

输出：

- runtime-visible evidence
- canonical answer candidate

固定约束：

- 主线程只消费标准化 hit
- 输出层不消费 raw parser text、raw tool block、raw index debug info

---

## 6. 新数据协议设计

## 6.1 统一文档协议

新增统一中间协议，暂定名：

- `NormalizedDocument`
- `NormalizedBlock`
- `NormalizedObjectRef`

建议最小字段：

### NormalizedDocument

- `doc_id`
- `source_path`
- `source_type`
- `collection`
- `version_digest`
- `title`
- `language`
- `page_count`
- `parser_backend`
- `quality_flags`

### NormalizedBlock

- `block_id`
- `doc_id`
- `block_type`
- `text`
- `normalized_text`
- `page`
- `section_path`
- `reading_order`
- `modality`
- `bbox`
- `parent_block_id`
- `object_ref_ids`
- `metadata`

### NormalizedObjectRef

- `object_ref_id`
- `doc_id`
- `object_type`
- `page`
- `section_path`
- `label`
- `anchor_block_ids`
- `metadata`

## 6.2 block_type 建议枚举

- `title`
- `heading`
- `paragraph`
- `list_item`
- `table`
- `table_caption`
- `figure`
- `figure_caption`
- `page_summary`
- `sheet_region`
- `json_field_group`

## 6.3 RetrievalHit 协议扩展

当前 [models.py](/D:/AI应用/langchain-agent/backend/RAG/models.py) 中的 `RetrievalHit` 过薄，后续应扩展：

- `hit_id`
- `doc_id`
- `block_id`
- `object_ref_id`
- `block_type`
- `section_path`
- `score_breakdown`
- `retrieval_modes`
- `parser_backend`
- `quality_flags`

这样上层才有能力判断：

- 这是正文块还是表格块
- 这是页摘要还是 OCR 残片
- 这是对象命中还是普通文本命中

## 6.4 本次先行固定的协议决策

为了减少实施时的反复返工，本次先固定以下设计决策：

### 决策 A. 新索引目录固定使用 `backend/storage/indexes_v2/`

原因：

- 语义清晰
- 与旧 `indexes/` 最容易并行对照
- 后续迁移完成后也便于受控切换

### 决策 B. 新中间缓存目录固定使用 `backend/storage/document_cache_v2/`

内容：

- `conversion/`
- `normalized/`
- `manifests/`

原因：

- 把“文档转换缓存”和“检索索引”彻底分开
- 避免以后再次把缓存和索引混到同一目录

### 决策 C. `knowledge` 先做三类逻辑单元

首批固定只做：

- `content_block`
- `object_block`
- `page_summary`

暂不在第一阶段扩展更多特殊 block 类型，避免初期过度设计。

### 决策 D. `durable_memory` 与 `session_memory` 第一阶段沿用 `content_block`

原因：

- 先解决 knowledge 的复杂文档问题
- memory collections 先不引入对象级协议，降低迁移面

### 决策 E. fallback 解析器只保留只读兜底能力

具体指：

- [backend/RAG/parser_adapter.py](/D:/AI应用/langchain-agent/backend/RAG/parser_adapter.py)
- [backend/pdf_analysis/parser.py](/D:/AI应用/langchain-agent/backend/pdf_analysis/parser.py)

第一阶段不再给它们增加新主能力，只允许：

- Docling 不可用时兜底
- 对照测试时补采样本

### 决策 F. retrieval core 对上统一暴露一个适配接口

固定接口目标：

- `retrieve(query, *, top_k, query_mode, collections) -> list[RetrievalHit]`

这样现有 runtime 不需要感知底层是 Docling 还是 legacy parser，也不需要感知底层是 LlamaIndex 还是旧 hybrid。

### 决策 G. 不单独新增厚重“清洗实体”，而是在现有协议上补充清洗决策字段

为避免把清洗再次做成黑盒，本次不额外引入新的顶层持久化对象类型。

固定做法：

- `NormalizedBlock` 增加或复用以下字段：
  - `clean_text`
  - `cleaning_flags`
  - `eligibility`
  - `drop_reasons`
  - `index_profiles`
- `normalized_manifest` 记录清洗统计与分布
- `IndexableUnit.metadata` 只保留与该 unit 直接相关的清洗结果

这样可以同时保证：

- 清洗决策可追踪
- 不再依赖后置文本补丁修结果
- 不为了“记录清洗”再平白扩出一套新协议

### 决策 H. 清洗放在 ingestion 前半段，不放在检索后半段

本次明确禁止两种错误做法：

1. 先把脏块全部建索引，再在 query 时靠 rerank 或 prompt 挡噪声。
2. 在 answer assembly 阶段再判断“这段像不像占位符”。 

固定链路：

`conversion -> normalized build -> block cleaning -> eligibility gating -> index projection -> indexing`

原因：

- 清洗的职责是降低索引体积、稳住 steady-state 成本、减少错召回。
- 只有在建索引前做可索引性判定，才能真正减少空摘要和噪声命中。
- 这也符合“结构修复优先于提示修复”的既有原则。

### 决策 I. 一个 block 可以被保留为对象证据，但不一定进入主 dense 索引

本次不采用“保留即全保留、丢弃即全丢弃”的二元思路，而采用最小投影原则：

- 对正文有语义价值的块：进入 `dense_main`，按需进入 `lexical_main`
- 对对象定位有价值但正文语义弱的块：仅进入 `object_anchor`
- 对页级概览有价值的块：参与 `page_summary_source`
- 对纯占位、纯装饰、纯噪声的块：直接 `drop`

这样可以同时解决两类问题：

- 避免图表占位符污染主索引
- 又不丢失表格、图片、页对象的定位能力

## 6.5 结构化清洗规则

本次采用的不是“一个 cleaner + 一串 regex”的旧路线，而是 4 级固定清洗：

### Level 1. 文本规范化

职责：

- 统一空白、换行、标题标记
- 清理明显的控制字符和不可见字符
- 折叠重复标点与重复空行

允许做的事：

- 不改变原始语义
- 只做字符级规范化

禁止做的事：

- 不做业务改写
- 不做 query-aware 改写

### Level 2. 结构噪声识别

重点识别：

- `<!-- image -->`
- `<!-- table -->`
- `<!-- formula-not-decoded -->`
- 页眉页脚、页码、版权脚注、目录编号孤块
- 纯装饰 heading，如单独的 `第一章`、`AI`、孤立编号
- OCR 乱码密集块

输出：

- `cleaning_flags`
- `drop_reasons`
- `quality_flags` 补充项

### Level 3. 可索引性判定

判定目标不是“这个块有没有文本”，而是“这个块是否适合进入目标索引视图”。

最小判定档位：

- `keep`
- `keep_object_only`
- `keep_summary_only`
- `drop`

默认规则：

- 正文段落、成型标题、成型列表：`keep`
- 表格/图片锚点与 caption：优先 `keep_object_only`
- 页面概览候选块：可同时标记 `keep_summary_only`
- 占位符、装饰块、乱码块：`drop`

### Level 4. 索引投影

在通过可索引性判定后，再决定投影到哪些索引视图：

- `dense_main`
- `lexical_main`
- `object_anchor`
- `page_summary_source`

固定约束：

- `page_summary_source` 只吃 `keep` 或高质量 `keep_summary_only` 块
- `dense_main` 不吃纯占位 object block
- `object_anchor` 可以保留 caption、label、anchor text

## 6.6 第一阶段固定阈值与丢弃规则

为避免实施时反复摇摆，第一阶段先锁定以下硬规则：

### 必丢块

- 文本精确等于 `<!-- image -->`
- 文本精确等于 `<!-- table -->`
- 文本精确等于 `<!-- formula-not-decoded -->`
- 清洗后为空
- 仅由页码、单个编号、单个章节序号组成且无上下文语义

### 默认不进主 dense 的块

- `figure`
- `table`
- `sheet_region`
- 纯 label/caption 且长度极短的对象块
- OCR 乱码占比明显过高的块

### 允许保留进主 dense 的块

- 有明确语义谓词的 paragraph
- 与主题强相关的 heading
- 可以独立成义的 list_item
- 经过清洗后仍具可读性的 caption 或摘要段

### 页摘要生成规则

- 只从通过 `keep` 的正文块聚合
- 单页候选块少于最小阈值时不生成页摘要，宁可缺省，不产噪声摘要
- 页摘要必须写入来源 block 数量与来源 block_id 列表，便于追溯

---

## 7. 检索策略重建

## 7.1 核心原则

新的检索策略不再以“先粗暴解析全文，再 fallback BM25”为主，而改为：

1. 先命中持久化 dense index。
2. 同步命中持久化 lexical index。
3. 使用 fusion retriever 合并。
4. 根据 block/object 类型做轻量后排序。
5. steady-state 不再触发全量原文重解析。

## 7.2 collection 设计

保留现有 collection 思路，但内部索引类型改造：

- `knowledge`
- `durable_memory`
- `session_memory`

其中 `knowledge` 再拆为逻辑子视图：

- `knowledge_blocks`
- `knowledge_objects`
- `knowledge_page_summaries`

注意：

- 这些可以共享底层存储，但在检索层需要可区分。
- 不要求一开始就做物理三套索引，可以先做逻辑标签隔离。

## 7.3 Query 模式

建议引入显式 query mode：

- `semantic_lookup`
- `page_grounded_lookup`
- `object_lookup`
- `document_overview`
- `table_lookup`

这个 mode 由主线程 route 决定，不由底层索引临场猜。

## 7.4 清洗与检索投影策略

为保证 v2 检索从一开始就是“少而准”的索引，不再沿用旧链路“先全量塞进去，再靠检索时补救”的思路。

固定策略如下：

1. `dense_main`
   - 只承载正文语义检索主视图
   - 目标是回答首问、综述问、概括问
2. `lexical_main`
   - 只补充关键词、术语、数字命中
   - 不承担纠正主索引噪声的职责
3. `object_anchor`
   - 承载图、表、页对象的定位锚点
   - 服务于 PDF 跟读、页内问答、对象跟进
4. `page_summary_source`
   - 不是独立在线索引，而是离线摘要素材池
   - 只在 rebuild 时生成页摘要，不在在线 query 时临时拼接

这意味着 query path 的职责也被锁定：

- `semantic_lookup` 优先 `dense_main + lexical_main`
- `page_grounded_lookup` 优先 `page_summary + dense_main`
- `object_lookup` 优先 `object_anchor`
- `document_overview` 优先页摘要和正文高质量块
- `table_lookup` 可以提高 `object_anchor` 与 `lexical_main` 的比重

---

## 8. 迁移策略

## 8.1 总体原则

分三步迁移：

1. 先建立新前处理和新索引，但不立即替换主路径。
2. 通过适配层让旧 router 能消费新 retrieval core。
3. 验证稳定后，再删除旧 parser/hybrid 主链。

## 8.1.1 迁移期间的固定开关策略

为保证切换过程稳定，本次预先定义 4 个阶段性开关：

- `vector_store_backend = qdrant | llamaindex | faiss`
- `document_conversion_backend = legacy | docling`
- `retrieval_core_backend = legacy | llamaindex_v2`
- `retrieval_shadow_compare = off | on`
- `retrieval_cutover_mode = legacy_only | shadow_read | v2_primary`

其中固定默认值也一并锁定，避免实施期再次漂移：

- `vector_store_backend = qdrant`
- `document_conversion_backend = docling`
- `QDRANT_URL` 为空时使用本地嵌入式 Qdrant
- `QDRANT_URL` 有值时连接远端 Qdrant 服务
- `QDRANT_COLLECTION_PREFIX = agent`

固定用法：

### `legacy_only`

- 主路径读旧链路
- 新链路可离线构建，但不参与线上返回

### `shadow_read`

- 主路径仍返回旧链路结果
- 新链路同步执行并记录对照指标

### `v2_primary`

- 主路径返回新链路结果
- 旧链路仅作为紧急回退

这样可以避免实施期靠手工注释代码来切换路径。

## 8.2 兼容窗口

迁移期间允许同时存在：

- 旧 `ParsedChunk`
- 新 `NormalizedDocument / NormalizedBlock`

但约束是：

- 旧协议只用于兼容和回退
- 新协议成为所有新索引的唯一输入

## 8.3 旧向量库与旧索引库处理原则

本次是协议级重建，不是原位小修，因此旧索引不能继续作为长期可信底座。

但迁移期间也不能一开始就直接删除旧库，否则会失去：

- 新旧召回效果对照基线
- 性能回归基线
- 失败时的快速 fallback
- 长场景问题复盘证据

因此采用三阶段处理策略：

### 阶段 A：冻结旧库，不再扩张职责

迁移启动后，旧索引目录进入“冻结态”：

- 允许读取
- 允许用于对照测试
- 允许作为紧急 fallback
- 不再继续往旧协议上追加新字段、新解析逻辑、新缓存分支

这意味着：

- 不再把旧 `parser_adapter + manual hybrid` 当成长期主路径继续演化
- 不再以修旧索引为主要方向做能力增强

### 阶段 B：新旧并行

新链路必须使用独立目录，不能覆盖旧索引目录。

建议：

- 旧路径继续保留在 `backend/storage/indexes/`
- 新路径迁移到单独的 `backend/storage/indexes_v2/` 或 `backend/storage/retrieval_v2/`

并行期要求：

- 新旧索引可同时存在
- 新旧查询结果可对比
- 新链路验证通过前，不删除旧产物

### 阶段 C：受控清理

只有在以下条件全部满足后，才允许删除旧库：

1. `knowledge` 新链路已通过 steady-state 延迟验证
2. 长场景关键问题已完成回归
3. 主路径已切到新 retrieval core
4. 旧链路不再承担生产读流量

最终清理对象包括：

- 旧 FAISS 文件
- 旧 LlamaIndex persist 文件
- 旧 BM25 文档缓存
- 旧协议绑定的 meta 文件
- 仅服务于旧 parser/hybrid 的中间缓存

## 8.3.1 新旧对照的固定观测项

并行期每次影子查询至少记录：

- `legacy_hit_count`
- `v2_hit_count`
- `legacy_top_sources`
- `v2_top_sources`
- `legacy_latency_ms`
- `v2_latency_ms`
- `query_mode`
- `collection`
- `semantic_diff_tag`

用途：

- 判断新链路是否只是“更快”而没有“更准”
- 判断新链路是否只是“更准”但召回范围异常变窄
- 为 cutover 提供量化证据

## 8.4 不允许的反模式

- 不允许继续往 `parser_adapter.py` 叠更多文件类型启发式补丁
- 不允许继续在 `registry.py` 里同时塞解析、切块、缓存、检索、持久化职责
- 不允许让 query engine 直接产出主线程 truth
- 不允许在新索引尚未完成验证前直接删除旧索引目录

---

## Part B. 执行计划

## 9. 分阶段计划

## Phase 0. 建立新协议与实验路径

目标：

- 建立 `document_conversion` 与 `normalized_ingestion` 新骨架
- 不影响现有主链
- 明确旧索引冻结、新索引新目录、双轨期读写边界

完成标准：

- 可以对 `knowledge/` 中一批样本文档输出结构化中间结果
- 能产出 `NormalizedDocument` 和 `NormalizedBlock`
- 已确定新旧索引目录分离策略

执行步骤：

1. 新建 `document_conversion/`、`normalized_ingestion/`、`retrieval_core/` 目录骨架
2. 新建 `indexes_v2/` 与 `document_cache_v2/` 目录
3. 定义统一协议 dataclasses
4. 在 config 中补齐新链路开关
5. 写最小 smoke test，验证协议对象能落盘

本阶段输入：

- 现有 `knowledge/`
- 现有 `CollectionConfig`

本阶段输出：

- 协议模型
- 新目录结构
- 开关和基础配置

不允许在本阶段做的事：

- 不直接替换 `RetrievalService`
- 不直接删除旧 parser
- 不直接切换主查询路径

## Phase 1. 重建前处理主链

目标：

- 用 Docling 接管 PDF / DOCX / PPTX / 图片 / 表格主转换路径
- 旧 parser 退到 fallback
- 锁定 block 级清洗与可索引性判定主链

完成标准：

- 样本文档的块结构明显优于当前 `ParsedChunk`
- PDF 页级与表格级信息能稳定进入统一协议
- 可以稳定区分 `keep / keep_object_only / keep_summary_only / drop`
- `normalized_manifest` 能输出清洗统计，不再只输出 block 数量

执行步骤：

1. 实现 `DoclingConverter`
2. 实现 `ConversionCache`
3. 实现 legacy fallback adapter
4. 实现 `NormalizedDocumentBuilder`
5. 实现 block 级文本规范化和结构噪声识别
6. 实现 `eligibility` 与 `index_profiles` 判定
7. 为 PDF、DOCX、PPTX、XLSX 各选一组样本做对照转换
8. 固定质量标记规则，例如 `ocr_heavy`、`table_dense`、`layout_complex`
9. 固定第一阶段必丢块和默认不进主 dense 的 block 类型清单

本阶段输入：

- `SourceFileRecord`

本阶段输出：

- `ConversionResult`
- `NormalizedDocument`
- `NormalizedBlock[]`
- `NormalizedObjectRef[]`
- 带清洗统计的 `normalized_manifest`

切换条件：

- Docling 主路径在样本集上稳定
- fallback 可用但不承担主能力

回退条件：

- Docling 对某类文档持续失败
- 统一协议字段无法覆盖关键结构信息

## Phase 2. 重建 ingestion 与索引

目标：

- 用 LlamaIndex 接管 ingestion、持久化、dense、BM25、fusion
- 用投影后的“可索引单元”替代“全 block 直灌”

完成标准：

- `knowledge` collection 的 steady-state 查询不再触发全量重解析
- dense / lexical / fusion 可分别观测
- 索引后端配置与磁盘产物一致
- 主索引 unit 总量明显收缩，噪声块比例明显下降
- 页摘要不再由占位块和 OCR 噪声驱动

执行步骤：

1. 实现基于 `eligibility/index_profiles` 的 `IndexableUnit` 生成器
2. 实现 LlamaIndex ingestion pipeline 封装
3. 实现 dense index build/load
4. 实现 lexical retriever build/load
5. 实现 fusion retrieval 封装
6. 实现 metadata manifest 与 digest 校验
7. 为 `knowledge` 单独跑全量 rebuild 和 steady-state query 基准
8. 输出 unit 分布报告：`dense_main/object_anchor/page_summary`
9. 对 rebuild 前后 unit 数、噪声数、延迟、top hit 质量做对照

本阶段输入：

- `NormalizedDocument`
- `NormalizedBlock[]`
- `NormalizedObjectRef[]`

本阶段输出：

- `knowledge` 的 `indexes_v2` 持久化产物
- dense / lexical / fused retriever 适配接口

切换条件：

- steady-state 查询不再重新解析原文
- top hits 质量不低于旧链路
- `dense_main` 中不再大量出现占位符和孤立装饰块
- `page_summary` 的来源块均可追溯且可读

回退条件：

- v2 索引构建不稳定
- v2 steady-state 延迟劣化明显
- block/object hits 严重偏离预期

## Phase 3. 适配现有 retrieval service

目标：

- 让现有 `RetrievalService` 和 `RAGQueryRouter` 消费新内核

完成标准：

- 对上接口基本不变
- 主线程 runtime 无需整体重写

执行步骤：

1. 在 `retrieval_core/adapters.py` 中实现 `RetrievalHit` 适配
2. 让 `RAG.registry` 退化为 backend wiring
3. 让 `RAG.router` 只保留 route/rewrite/collection selection
4. 在 `RetrievalService` 中加入 `legacy_only/shadow_read/v2_primary` 模式
5. 加影子对比日志与观测字段

本阶段输入：

- 新 retrieval core
- 现有 router/runtime

本阶段输出：

- 旧接口兼容层
- 新旧双读能力

切换条件：

- runtime 对新 `RetrievalHit` 无兼容性问题
- 影子对比数据稳定

回退条件：

- 新 `RetrievalHit` 破坏了上层 answer assembly
- runtime 依赖旧薄对象隐式行为

## Phase 4. 扩展到 memory collections

目标：

- `durable_memory`
- `session_memory`

完成标准：

- memory collections 与 knowledge 使用统一索引生命周期
- 但主线程绑定与续接逻辑不下沉到检索内核

执行步骤：

1. 为 `durable_memory` 接入统一 ingestion pipeline
2. 为 `session_memory` 接入统一 ingestion pipeline
3. 先只迁移 `content_block`
4. 验证 memory recall 不受 `knowledge` 复杂对象协议影响

本阶段输入：

- `durable_memory`
- `session_memory`

本阶段输出：

- memory collections 的 v2 索引

切换条件：

- memory recall 稳定
- follow-up owner 不受检索层污染

回退条件：

- memory recall 质量明显下降
- session snapshot 与新 retrieval 产生冲突

## Phase 5. 清理旧链路

目标：

- 删除旧的主解析和旧 hybrid 主路径

完成标准：

- 没有关键查询依赖旧 `parser_adapter + manual bm25 + manual fusion`

执行步骤：

1. 将主路径切到 `v2_primary`
2. 保留一个短暂观察窗口
3. 冻结旧链路写入
4. 删除旧 parser/hybrid 的主路径调用
5. 删除旧索引产物与中间缓存
6. 更新文档与运维说明

本阶段输入：

- 稳定的 v2 主路径

本阶段输出：

- 单一检索真相
- 清理后的存储目录

不允许在本阶段做的事：

- 不允许保留“两套都可能是主路径”的模糊状态
- 不允许只删文件、不删代码入口

## 9A. 实施顺序锁定

为防止执行期跑偏，整个实施顺序固定为：

1. 先协议
2. 再转换
3. 再缓存
4. 再索引
5. 再适配
6. 再双读
7. 再切主
8. 最后清理

严禁跳序：

- 不允许先改 runtime 再补协议
- 不允许先删旧索引再做双读
- 不允许先改 answer 层来掩盖 retrieval 底层问题

## 9B. 每阶段产物清单

每个阶段必须交付 4 类产物：

1. 代码产物
2. 配置产物
3. 可观测产物
4. 验证产物

示例：

### Phase 1

- 代码产物：`DoclingConverter`、协议模型、fallback adapter
- 配置产物：Docling 开关、缓存目录配置
- 可观测产物：conversion backend、cache hit、quality flags
- 验证产物：样本文档转换对照结果

### Phase 2

- 代码产物：v2 ingestion/index/retriever
- 配置产物：v2 index root、retrieval backend 开关
- 可观测产物：dense/lexical/fusion latency 与 hit count
- 验证产物：steady-state query benchmark

## 9C. Cutover 与回退流程

切主流程固定为：

1. `legacy_only`
2. `shadow_read`
3. `v2_primary`
4. 观察窗口
5. 清理旧链路

每一步都必须满足：

- 有明确日志
- 有明确指标
- 有明确回退点

从 `v2_primary` 回退到 `legacy_only` 的触发条件固定为：

- 关键查询空召回率异常上升
- steady-state 延迟明显失控
- 主线程语义问题新增且可追溯到 retrieval v2

回退时禁止：

- 手工修改索引目录覆盖旧库
- 手工替换 manifest 伪装成回退
- 只改配置不记录事件

---

## 10. 逐文件执行清单

## 10.1 新增模块

### `backend/document_conversion/`

新增：

- `models.py`
- `docling_converter.py`
- `quality.py`
- `cache.py`

职责：

- 定义统一结构化文档协议
- 封装 Docling 转换
- 记录转换质量标记和缓存

### `backend/normalized_ingestion/`

新增：

- `models.py`
- `builder.py`
- `chunking.py`
- `eligibility.py`
- `summaries.py`

职责：

- 把 Docling 结果规范化为 ingestion 输入
- 生成 block/object/page-summary 等结构
- 完成 block 清洗、可索引性判定与索引投影

### `backend/retrieval_core/`

新增：

- `llamaindex_backend.py`
- `index_store.py`
- `retrievers.py`
- `adapters.py`

职责：

- 封装 LlamaIndex ingestion/index/retrieval
- 向旧 `RetrievalHit` 协议提供适配层

### `backend/storage/indexes_v2/` 或 `backend/storage/retrieval_v2/`

新增：

- `knowledge/`
- `durable_memory/`
- `session_memory/`

职责：

- 承载新协议下的持久化索引
- 与旧 `backend/storage/indexes/` 目录物理隔离
- 支持迁移期间的新旧对照与受控切换

## 10.2 重点改造模块

### [backend/RAG/parser_adapter.py](/D:/AI应用/langchain-agent/backend/RAG/parser_adapter.py)

改造方向：

- 不再作为主解析器
- 改成兼容 fallback 层
- 最终仅在 Docling 不可用时启用
- 不再承担主清洗逻辑

### [backend/pdf_analysis/parser.py](/D:/AI应用/langchain-agent/backend/pdf_analysis/parser.py)

改造方向：

- 从主 PDF 解析器降级为 fallback / emergency parser
- 保留本地应急页文本抽取能力

### [backend/RAG/registry.py](/D:/AI应用/langchain-agent/backend/RAG/registry.py)

改造方向：

- 拆掉解析、缓存、BM25、fusion 的混合职责
- 变成 collection registry + backend wiring

### [backend/RAG/router.py](/D:/AI应用/langchain-agent/backend/RAG/router.py)

改造方向：

- 保留 collection routing
- 保留 query rewrite
- 不再自己实现底层 hybrid lifecycle

### [backend/retrieval/service.py](/D:/AI应用/langchain-agent/backend/retrieval/service.py)

改造方向：

- 继续作为统一入口
- 内部改接新 retrieval core
- 不允许在服务层临时补做 block 清洗

### [backend/RAG/models.py](/D:/AI应用/langchain-agent/backend/RAG/models.py)

改造方向：

- 扩展 `RetrievalHit`
- 增加新协议向旧接口的桥接字段

### [backend/config.py](/D:/AI应用/langchain-agent/backend/config.py)

改造方向：

- 去掉当前“只识别 faiss|llamaindex”但 env 又可能配其它值的静默错配
- 将 `qdrant` 固化为默认 dense backend，并补齐远端/本地配置项
- 增加文档转换和新检索内核的配置项
- 明确 fallback 策略和 timeout

## 10.3 暂不直接改动但要验证的模块

- [backend/understanding/task_understanding.py](/D:/AI应用/langchain-agent/backend/understanding/task_understanding.py)
- [backend/query/runtime.py](/D:/AI应用/langchain-agent/backend/query/runtime.py)
- [backend/query/output_boundary.py](/D:/AI应用/langchain-agent/backend/query/output_boundary.py)
- [backend/query/output_classifier.py](/D:/AI应用/langchain-agent/backend/query/output_classifier.py)

理由：

- 本次先重建 RAG 底层，不提前改主线程控制。
- 但要验证底层变更是否减少了上层坏答案输入。

---

## 11. 验证策略

## 11.1 基础验证

- 单文档转换结果质量
- 多格式文档转换一致性
- 索引构建和重载一致性
- steady-state 查询延迟
- 清洗前后 unit 数对比
- 必丢块命中率与误杀率抽检

## 11.2 场景验证

重点回归现有长场景问题：

- `LS-SEM-001`
- `LS-SEM-002`
- `LS-SEM-003`
- `LS-SEM-004`
- `LS-SEM-005`

验证目标：

- 首问不再因 dense miss 直接掉进长耗时空召回
- PDF 跟读命中的是结构块，不是纯 OCR 残片
- 结构化数据问答命中的是对象块，而不是扁平文本表
- `LS-SEM-001` 中首问 top hits 不再出现协议占位片段
- `LS-SEM-003` 中 PDF 总览和页问答的摘要来源可回溯到有效块

## 11.3 观测字段

建议新增可观测字段：

- `conversion_backend`
- `conversion_cache_hit`
- `normalized_block_count`
- `eligible_block_count`
- `dropped_block_count`
- `dense_unit_count`
- `object_anchor_count`
- `page_summary_source_count`
- `retrieval_mode`
- `retrieval_backend`
- `dense_hit_count`
- `lexical_hit_count`
- `fusion_hit_count`
- `retrieval_latency_ms`
- `fallback_parser_used`

---

## 12. 风险与控制

## 12.1 主要风险

- Docling 引入后，首轮索引构建成本可能上升
- 文档结构更丰富后，chunk 数量可能增多
- 新旧协议共存期间，容易出现双写和双解释

## 12.2 控制手段

- 先做离线转换缓存，再做在线索引
- 先重建 `knowledge`，后迁移 `memory`
- 保留旧 parser 作为 fallback，但不允许继续扩张其职责
- 先做适配层替换，再做旧链路删除

---

## Part C. 推荐决策

最终建议：

1. 采用 `Docling + LlamaIndex + 现有主线程 runtime` 的三层组合。
2. 本次重建先从 `knowledge` collection 开始，不一次性改动 memory 主链。
3. 先重建前处理和索引，再回头修答案层次生问题。

一句话总结：

> 这次不是把 RAG“换个库”，而是把“文本抽取式 RAG”重建成“结构化文档转换 + 标准化检索内核 + 主线程显式控制”的新底座。
