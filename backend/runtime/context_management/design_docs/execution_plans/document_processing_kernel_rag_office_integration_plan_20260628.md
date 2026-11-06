# 文档处理内核与 RAG/Office 整合计划

日期：2026-06-28

## 1. 问题定义

当前系统已经存在两类文档能力：

1. RAG 知识库链路：负责把 PDF、DOCX、PPTX、XLSX、CSV、图片、Markdown 等资料转换、清洗、分块、索引、检索和打包证据。
2. 新规划的 Office 文档处理链路：负责 Word、Excel、PowerPoint、PDF 的读取、编辑、转换、生成和渲染验证。

如果直接新增 `office_document_runtime`，会出现结构性问题：

- RAG 链路如果继续使用旧 `DoclingConverter`、旧 `MultimodalParserAdapter`、`NormalizedDocumentBuilder` 各自解析文档，会形成重复解析权威。
- Office 链路会再做一套 `FormatDetector`、`OfficeDocumentIR`、adapter 解析。
- 同一份文档会有两份事实来源：一份用于检索，一份用于编辑。
- 路由层可能把“读取文档内容”“知识检索”“编辑文档”“表格计算”混在一起做二次判断。

正确的系统属性应该是：

```text
统一文档处理内核拥有文档事实；
RAG 只消费索引投影；
Office runtime 只消费编辑/转换投影；
PDF 深读与 Excel 计算继续作为专项能力，但它们也应接收统一文档内核的对象引用和诊断。
```

## 2. 当前 RAG 链路事实

现有 RAG 链路文件与职责：

- `backend/capability_system/capabilities/retrieval/service.py`
  - `RetrievalService` 负责构建 query plan、调用 retrieval backend、rerank、生成 evidence pack 诊断。
- `backend/capability_system/capabilities/retrieval/router.py`
  - `RAGQueryRouter` 负责 query rewrite 后选择 collection、filter、policy。
- `backend/capability_system/capabilities/retrieval/query_rewriter.py`
  - `QueryRewriter` 通过规则识别 `table/pdf_page/document/memory/general`。
- `backend/knowledge_system/indexing/bootstrap.py`
  - `RetrievalBootstrapper` 负责 source discovery、conversion、normalization、chunking、index build。
- `backend/capability_system/capabilities/document_processing/adapters/conversion_resource.py`
  - `DocumentConversionResource` 负责 PDF page-aware parser、Docling、local parser resource 三段式转换。
- `backend/knowledge_system/conversion/models.py`
  - `ConversionResult` 是当前 RAG 解析输出的结构合同。
- `backend/knowledge_system/ingestion/builder.py`
  - `NormalizedDocumentBuilder` 把 `ConversionResult` 转成 `NormalizedDocument/NormalizedBlock/NormalizedObjectRef`。
- `backend/knowledge_system/ingestion/chunking.py`
  - `build_indexable_units` 构造 `content_block/page_summary/parent_section/object_block/document_summary`。
- `backend/capability_system/capabilities/retrieval/evidence_packager.py`
  - 将 retrieval results 转成面向回答的 evidence pack。

现有 RAG 算法顺序：

```text
discover_source_files
-> DocumentProcessingKernel.parse
-> DocumentConversionResource.convert
-> ConversionResult
-> NormalizedDocumentBuilder.build
-> NormalizedDocument / NormalizedBlock / NormalizedObjectRef
-> build_indexable_units
-> LlamaIndexRetrievalBackend.build_collection
-> QueryRewriter / RAGQueryRouter
-> RetrievalBackend.retrieve
-> rerank
-> evidence_packager
```

这个链路已经成熟，不能废掉。但它的“解析权威”应被统一文档处理内核接管。

## 3. 目标架构

新增统一上游：

```text
backend/capability_system/capabilities/document_processing/
  kernel.py
  models.py
  format_detector.py
  ir_builder.py
  projections/
    rag_projection.py
    office_projection.py
    evidence_projection.py
  adapters/
    word.py
    excel.py
    powerpoint.py
    pdf.py
    text.py
    image.py
```

权威链路：

```text
SourceFileRecord
-> DocumentProcessingKernel.parse()
-> DocumentProcessingBundle
   ├─ DocumentFormat
   ├─ OfficeDocumentIR
   ├─ DocumentDiagnostics
   ├─ RagProjection
   ├─ OfficeProjection
   └─ EvidenceProjection
```

RAG 使用：

```text
DocumentProcessingBundle.RagProjection
-> ConversionResult
-> NormalizedDocumentBuilder
-> build_indexable_units
-> retrieval index
```

Office runtime 使用：

```text
DocumentProcessingBundle.OfficeProjection
-> OfficeDocumentIR
-> OfficePatchPlan
-> PatchExecutor
-> VerificationEngine
```

证据系统使用：

```text
DocumentProcessingBundle.EvidenceProjection
-> SourceObjectRef / EvidenceArtifact / object handles
```

## 4. 统一数据合同

### DocumentProcessingBundle

```text
DocumentProcessingBundle
  bundle_id
  source_record
  detected_format
  office_ir
  rag_projection
  office_projection
  evidence_projection
  diagnostics
  parser_route
  quality_flags
```

### RagProjection

RAG 投影必须保持当前索引链路可消费：

```text
RagProjection
  conversion_result
  normalized_document_hint
  index_quality_hints
```

第一阶段不删除 `ConversionResult`，而是由 `DocumentProcessingKernel` 生成它。这样 `RetrievalBootstrapper` 只需要替换转换来源，不必同时重写 indexing。

### OfficeProjection

```text
OfficeProjection
  office_ir
  editable
  supported_actions
  unsupported_actions
  preservation_warnings
```

### EvidenceProjection

```text
EvidenceProjection
  source_object
  object_refs
  artifact_candidates
  binding_candidates
```

## 5. 算法整合策略

### 5.1 解析算法统一

原先 RAG 的 `DoclingConverter.convert()` 已迁移为文档处理层的 `DocumentConversionResource.convert()`，不再由 RAG 直接拥有完整解析决策：

```text
DocumentProcessingKernel.parse(record)
  -> detect format
  -> choose adapter
  -> build OfficeDocumentIR
  -> project IR to ConversionResult
  -> if IR adapter unavailable, call DocumentConversionResource as parser resource
```

注意：fallback 只能产生 degraded diagnostics，不能悄悄成为长期主链路。

### 5.2 清洗与分块算法保留

`NormalizedDocumentBuilder` 和 `build_indexable_units` 继续保留，因为它们是 RAG 索引算法，不是底层文档解析算法。

但它们的输入来源改为：

```text
RagProjection.conversion_result
```

而不是散落的 parser 输出。

### 5.3 Query rewrite 与路由保留但降权

`QueryRewriter` 仍可识别 table/document/pdf_page/memory，但它不能决定“文档如何解析”。

目标职责：

- QueryRewriter：只做检索意图和关键词扩展。
- RAGQueryRouter：只做检索 collection/filter/policy。
- DocumentProcessingKernel：只做文档事实解析。
- OfficeDocumentRuntime：只做办公文档操作计划与执行。

### 5.4 Evidence pack 统一引用

RAG 检索结果中的 metadata 应逐步加入统一文档内核字段：

```text
document_bundle_id
ir_part_id
ir_block_id
ir_table_id
anchor_id
source_object_id
```

这样后续“根据检索证据编辑原文档某段”可以从 evidence 反向定位到 Office IR anchor，而不是重新模糊匹配文本。

## 6. 权威边界

| 层级 | 当前模块 | 目标职责 | 不允许做 |
| --- | --- | --- | --- |
| 文件事实 | 新 `document_processing_kernel` | 识别格式、构建 IR、生成投影 | 不回答用户、不做检索排序 |
| RAG 索引 | `knowledge_system.ingestion/indexing` | 清洗、分块、层级索引 | 不重新解析 Office 文件 |
| RAG 查询 | `RetrievalService/RAGQueryRouter` | query rewrite、filter、retrieve、rerank | 不决定编辑动作 |
| Office 操作 | 新 `office_document_runtime` | patch plan、执行、验证 | 不做知识库检索排序 |
| PDF 深读 | `pdf-analysis` | 页级/章节级阅读问答 | 不编辑 PDF 正文 |
| Excel 分析 | `structured-data-analysis` | 表格计算、筛选、汇总 | 不处理 Word/PPT 编辑 |
| Evidence | `evidence` | 统一产物、来源、绑定 | 不偷偷改变任务意图 |

## 7. 目标固定执行流

### 7.1 知识库摄取

```text
discover_source_files
-> DocumentProcessingKernel.parse(record)
-> RagProjection.conversion_result
-> NormalizedDocumentBuilder.build
-> build_indexable_units
-> RetrievalBackend.build_collection
```

### 7.2 RAG 查询

```text
user query
-> QueryRewriter
-> RAGQueryRouter
-> RetrievalBackend.retrieve
-> rerank
-> EvidencePack
```

RAG 查询不触发 Office 编辑。

### 7.3 办公文档编辑/生成

```text
user request
-> request signals detect office document action
-> DocumentProcessingKernel.parse(source)
-> OfficeProjection.office_ir
-> IntentCompiler
-> OfficePatchPlan
-> PatchExecutor
-> VerificationEngine
-> EvidenceProjection / artifact output
```

### 7.4 RAG 证据驱动的文档修改

```text
retrieve evidence
-> evidence contains anchor_id / ir_block_id
-> Office runtime resolves anchor
-> patch plan
-> execute
-> verify
```

如果证据没有稳定 anchor，不允许直接按文本模糊替换，必须返回候选或要求澄清。

## 8. 文件级实施清单

### 阶段 A：文档内核模型

新增：

```text
backend/capability_system/capabilities/document_processing/models.py
backend/capability_system/capabilities/document_processing/format_detector.py
backend/capability_system/capabilities/document_processing/kernel.py
backend/capability_system/capabilities/document_processing/ir_builder.py
backend/capability_system/capabilities/document_processing/projections/rag_projection.py
backend/capability_system/capabilities/document_processing/projections/office_projection.py
backend/capability_system/capabilities/document_processing/projections/evidence_projection.py
```

完成标准：

- 能识别 PDF、OOXML、OLE、文本、图片。
- 能生成 `DocumentProcessingBundle`。
- 能从 IR 投影出 `ConversionResult`。

### 阶段 B：RAG 摄取切换

修改：

```text
backend/knowledge_system/indexing/bootstrap.py
backend/capability_system/capabilities/document_processing/adapters/conversion_resource.py
backend/knowledge_system/conversion/cache.py
```

目标：

- `RetrievalBootstrapper._load_or_convert()` 优先调用 `DocumentProcessingKernel`。
- `DocumentConversionResource` 保留为 kernel 内部 parser resource；旧 `DoclingConverter` 公共入口已清理。
- conversion cache 增加 bundle/version 信息，但保留 `ConversionResult` 兼容读取。

完成标准：

- RAG index rebuild 的输出统计不倒退。
- parser route 能显示 `document_kernel -> adapter/docling/fallback`。

### 阶段 C：Office runtime 接入内核

新增或修改：

```text
backend/capability_system/capabilities/office_document/runtime.py
backend/capability_system/capabilities/office_document/models.py
backend/capability_system/capabilities/office_document/planner.py
backend/capability_system/capabilities/office_document/verifier.py
backend/capability_system/capabilities/office_document/adapters/*
```

目标：

- Office runtime 不自行解析文件，只消费 `DocumentProcessingBundle.office_projection`。
- 编辑与生成动作必须走 patch plan。

当前实施状态：

- 已新增 `OfficeDocumentRuntime`、`OfficeDocumentRequest`、`OfficeDocumentResult`。
- `inspect/read` 只消费 `DocumentProcessingKernel` 的 `office_projection` 和 `rag_projection`。
- 已新增 `OfficePatchPlanner`、`OfficePatchExecutor`、`OfficeVerificationEngine`。
- `edit` 已支持第一批真实 patch 操作：
  - Word: `replace_paragraph_text`、`insert_paragraph_after`、`append_paragraph`、`append_section`。
  - Excel: `update_cell`、`set_formula`、`append_rows`、`create_sheet`。
  - PowerPoint: `replace_shape_text`、`add_slide`、`insert_text_box`。
  - PDF: `delete_pages`、`reorder_pages`、`split_pages`、`merge_pdfs`。
- 写入路径已使用 `office_write` 快速 parse profile，只做格式检测和最小 bundle，不触发重型 RAG/OCR 解析。
- 后续更复杂的 planner、executor、verifier 必须继续挂在该 runtime 下，不能回到 RAG 或 parser resource。

### 阶段 D：证据锚点打通

修改：

```text
backend/knowledge_system/ingestion/builder.py
backend/knowledge_system/ingestion/chunking.py
backend/capability_system/capabilities/retrieval/evidence_packager.py
backend/evidence/adapter.py
```

目标：

- IndexableUnit metadata 中携带 `document_bundle_id`、`ir_block_id`、`anchor_id`。
- EvidenceItem metadata 保留这些字段。
- Office runtime 可从 evidence 反查 anchor。

### 阶段 E：能力注册与路由

修改：

```text
backend/capability_system/mcp/local_registry.py
backend/capability_system/mcp/server/server.py
backend/permissions/operations.py
backend/permissions/operation_packages.py
backend/task_system/environments/default_environments.py
backend/task_system/environments/prompt_resources.py
backend/agent_system/profiles/runtime_profile_registry.py
backend/runtime/request_signals/request_signals.py
backend/task_system/contracts/task_requirement_contracts.py
backend/task_system/contracts/execution_obligation.py
```

目标：

- `.doc/.docx/.xls/.xlsx/.ppt/.pptx/.pdf` 被识别为文档材料。
- 查询类进 RAG/PDF/structured-data。
- 编辑、生成、转换、验收类由办公任务环境授予 `pkg.office.document`，再进入 Office runtime。

## 9. 迁移与切换规则

### Shadow 阶段

- DocumentProcessingKernel 和现有 Docling/RAG 转换并行运行。
- 记录 projection 差异，但 RAG 仍使用旧 ConversionResult。
- 不改变用户行为。

### Cutover 阶段

- `RetrievalBootstrapper` 改为使用 kernel 产出的 `RagProjection.conversion_result`。
- Docling 只作为 kernel parser resource，不再由 RAG 直接决策。

### Cleanup 阶段

- 删除或改名不再拥有解析权威的 fallback 入口。
- 保留必须的 parser adapter，但其身份必须是 `resource adapter`，不能是 `decision owner`。

已执行清理：

- `backend/capability_system/capabilities/retrieval/parser_adapter.py` 已迁移为 `backend/capability_system/capabilities/document_processing/adapters/local_parser.py`。
- `backend/capability_system/capabilities/retrieval/cleaner.py` 已迁移为 `backend/capability_system/capabilities/document_processing/content_cleaner.py`。
- `backend/knowledge_system/conversion/docling_converter.py` 已迁移为 `backend/capability_system/capabilities/document_processing/adapters/conversion_resource.py`。
- `RetrievalBootstrapper` 和 retrieval CLI 只通过 `DocumentProcessingKernel` 获取文档解析结果。

## 10. 验证矩阵

不新增回归测试文件。按项目规则使用真实物理运行和代码审查验证：

- RAG rebuild: 对 knowledge collection 执行重建，确认 converted/normalized/indexable 统计正常。
- RAG query: 文档查询、表格查询、页级查询各跑一次，确认 evidence pack 有稳定来源。
- Word: 读取 docx，生成 IR，投影 RAG blocks，执行段落编辑，导出 PDF 验证。
- Excel: 读取 xlsx，识别 sheet/range，投影表格 blocks，结构化数据分析仍可用，编辑 cell 后验证。
- PowerPoint: 读取 pptx，识别 slide/shape，投影 slide text，编辑 shape 文本后验证。
- PDF: 页级抽取、表格抽取、RAG page_summary、PDF 深读能力保持。
- 失败路径: 缺 converter、anchor ambiguous、formula recalculation unavailable 均返回 typed degraded reason。

## 11. 反模式清单

实施时禁止：

- 在 Office runtime 中复制一套 RAG 分块算法。
- 在 RAG converter 中复制一套 Office 编辑 IR。
- 让 QueryRewriter 决定文件解析方式。
- 让 adapter 自己解释用户意图。
- 让 fallback 静默改变解析路线但不记录 diagnostics。
- 为了保留旧链路而让两个解析权威长期并存。

## 12. 结论

整合方向是：

```text
DocumentProcessingKernel 是文档事实权威；
RAG 是检索投影；
Office runtime 是编辑/转换投影；
Evidence 是跨能力引用和产物账本。
```

这样既保留现有 RAG 系统的成熟索引、检索和证据能力，又让新 Office 文档算法成为统一上游，避免重复解析和新旧链路互相干扰。
