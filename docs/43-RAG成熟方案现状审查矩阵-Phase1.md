# RAG 成熟方案现状审查矩阵 Phase 1

> 编写日期：2026-04-22  
> 对照基线：`docs/42-RAG成熟方案对照与改造执行清单.md`  
> 审查目标：判断当前正式链路哪些部分已经符合成熟方案，哪些只是部分符合，哪些仍明显不符合，并据此锁定下一阶段的实施起点。

---

## 1. 审查结论总览

当前系统并不是“完全没有基础”，但离成熟 RAG 主链还有明显差距。

整体判断如下：

- 解析层：`部分符合`
- 结构清洗层：`部分符合`
- 分层节点层：`不符合`
- sparse / lexical 检索层：`不符合`
- hybrid 融合层：`不符合`
- rerank 层：`部分符合`
- 服务切换与旧入口治理：`部分符合`
- benchmark 与回归层：`部分符合`

核心结论：

1. 当前链路已经具备“正式解析 -> normalized ingestion -> 检索”的基础骨架。
2. 但检索主链仍是 `qdrant dense + application lexical BM25`，这和目标方案不一致。
3. 当前还没有真正的父块/子块分层节点体系，检索结果仍主要绑在单层 block 上。
4. benchmark 虽然已经接入 dense health 检查，但仍没有完全走正式解析能力。
5. 现阶段最优先的实施起点不是继续调 rerank，而是先重建结构清洗输出契约与分层节点模型。

---

## 2. 分模块审查矩阵

## 2.1 文档解析层

文件：

- [docling_converter.py](/D:/AI应用/langchain-agent/backend/document_conversion/docling_converter.py)

状态：

- `部分符合`

已符合点：

- 具备 `Docling -> PDF parser -> legacy fallback` 的多级解析顺序。
- 对 PDF 有可用性检查，不是无脑信任单一解析器。
- 已能输出 `ConversionResult` 与结构化 `ConversionBlock`。

不符合点：

- `_blocks_from_markdown()` 仍是按空行切段的轻量拆分，不是正式结构解析模型。
- fallback 里仍保留 `legacy_adapter`，说明旧链路还没彻底退出职责。
- Docling / MinerU 的职责边界还没有被写成稳定的数据契约。

判断：

- 解析入口有了，但“结构优先”的正式输出契约还没锁死。

## 2.2 Normalized Document Builder

文件：

- [builder.py](/D:/AI应用/langchain-agent/backend/normalized_ingestion/builder.py)

状态：

- `部分符合`

已符合点：

- 已有 `NormalizedDocument / NormalizedBlock / NormalizedObjectRef` 三类对象。
- object 型 block 已经被独立抽出，不再完全混在正文里。
- builder 已负责从 conversion 产物到 normalized 产物的正式收口。

不符合点：

- builder 仍主要在“标准化字段”，还没有承担“层级节点生成”职责。
- 当前 block 与 object 已分离，但 doc / parent / leaf 三层结构还未建立。

判断：

- builder 是合适的正式收口点，但还没升级成目标架构里真正的层级建模层。

## 2.3 Normalized Models

文件：

- [models.py](/D:/AI应用/langchain-agent/backend/normalized_ingestion/models.py)

状态：

- `部分符合`

已符合点：

- `NormalizedBlock` 已预留 `parent_block_id`。
- `IndexableUnit` 已具备 `doc_id / block_id / object_ref_id / page / section_path` 这些正式字段。

不符合点：

- `parent_block_id` 只是字段预留，没有成为真实运行中的正式关系。
- `IndexableUnit` 仍是单层索引对象，没有父子层级节点定义。
- 当前模型里没有显式的“文档节点 / 父块节点 / 叶子块节点”类型系统。

判断：

- 数据模型已经预留了升级空间，但实际还停留在单层 block 检索时代。

## 2.4 Chunking / Indexable Units

文件：

- [chunking.py](/D:/AI应用/langchain-agent/backend/normalized_ingestion/chunking.py)

状态：

- `不符合`

已符合点：

- 已能生成 `content_block / object_block / page_summary` 三类 indexable unit。
- 已将 title / section / parser_backend 等元数据送入 unit metadata。

不符合点：

- 当前主索引单元仍是单层 `content_block`。
- `page_summary` 是补充视图，不是父块/子块正式层级。
- 没有显式叶子节点召回后回填父块的机制。
- 仍缺少成熟方案需要的层级节点切分策略。

判断：

- 这是当前正式链路里最重要的结构缺口之一。

## 2.5 Retrieval Backend

文件：

- [llamaindex_backend.py](/D:/AI应用/langchain-agent/backend/retrieval_core/llamaindex_backend.py)

状态：

- `不符合`

已符合点：

- dense 构建、持久化、健康检查已经进入正式后端。
- retrieval 已支持 `semantic_lookup / page_grounded_lookup / table_lookup / document_overview` 四类模式。
- 有聚合、融合、breakdown 这些观测基础。

不符合点：

- 文件头部明写当前是 `qdrant dense + application lexical BM25`，这本身就偏离目标方案。
- `retrieve()` 仍是 `dense -> lexical -> fuse -> coalesce`，说明当前返回主链还是旧的融合设计。
- hybrid 还没有迁到 Qdrant 原生 sparse / hybrid。
- `_fusion_weights()` 仍是应用层手工权重，不是正式 hybrid 底座。

判断：

- 这是当前与成熟方案偏差最大的核心模块。

## 2.6 Lexical / Sparse 层

文件：

- [lexical.py](/D:/AI应用/langchain-agent/backend/retrieval_core/lexical.py)

状态：

- `不符合`

已符合点：

- tokenization 已比最早版本更干净。
- `build_searchable_text()` 已开始注入 title / section / header。

不符合点：

- 仍是应用层自维护 lexical index。
- 同一文件里同时存在 BM25、分数归一化、fusion payload 等逻辑，职责过厚。
- 当前 sparse 能力还不是正式底座，只是过渡实现。

判断：

- 该模块最多适合作为过渡 fallback，不应继续承担长期正式 sparse 主职责。

## 2.7 Retrieval Service

文件：

- [service.py](/D:/AI应用/langchain-agent/backend/retrieval/service.py)

状态：

- `部分符合`

已符合点：

- 已有 v2 主链入口 `_retrieve_v2_from_plan()`。
- v2 结果已能统一进入服务层并接上 rerank。

不符合点：

- 仍保留 `legacy_only / shadow_read / v2_primary` 三种切换模式。
- `router.retrieve()` 旧入口仍在正式服务里占据分支路径。
- 说明旧系统虽然不是主目标，但还没真正退出主服务控制面。

判断：

- 服务层已经开始切新链路，但旧入口治理还没完成。

## 2.8 Benchmark / SciFact Eval

文件：

- [scifact_v2_eval.py](/D:/AI应用/langchain-agent/backend/tests/scifact_v2_eval.py)

状态：

- `部分符合`

已符合点：

- 已走 `NormalizedDocumentBuilder + build_indexable_units` 正式 ingestion 路径。
- 已加入 `dense_health` 与 `benchmark_mode`，能阻断 dense 掉线时的假评测。

不符合点：

- `_build_units()` 里直接 `DoclingConverter(enabled=False)`。
- benchmark 仍是通过 `_blocks_from_markdown()` 手工构造 conversion block，不是正式解析器能力。
- 这意味着 benchmark 还没有完整覆盖“正式解析 -> 正式清洗 -> 正式索引”的全链路。

判断：

- benchmark 已经比之前健康很多，但还不算完全贴近未来正式系统。

---

## 3. 当前最关键的坏点排序

按对目标方案的破坏程度排序，当前最该优先解决的是：

1. `chunking / models` 还没有真正的分层节点体系。
2. `llamaindex_backend` 仍然建立在应用层 lexical 与手工 fusion 上。
3. `scifact_v2_eval` 还没有完全走正式解析能力。
4. `retrieval service` 仍保留旧入口切换分支。
5. `docling_converter` 的结构输出契约还不够刚性。

---

## 4. 下一阶段的正式实施起点

下一阶段不建议从 rerank 开始，也不建议继续先调参数。

建议正式起点如下：

### Step 1. 先锁结构清洗输出契约

起点文件：

- [docling_converter.py](/D:/AI应用/langchain-agent/backend/document_conversion/docling_converter.py)
- [builder.py](/D:/AI应用/langchain-agent/backend/normalized_ingestion/builder.py)
- [models.py](/D:/AI应用/langchain-agent/backend/normalized_ingestion/models.py)

目标：

- 把 `title / section / page / object_ref / quality_flags / parser_backend` 固定成正式契约。
- 明确 Docling 与 MinerU 的补位关系。

### Step 2. 把单层 block 升级为分层节点

起点文件：

- [models.py](/D:/AI应用/langchain-agent/backend/normalized_ingestion/models.py)
- [chunking.py](/D:/AI应用/langchain-agent/backend/normalized_ingestion/chunking.py)

目标：

- 正式定义文档节点、父块节点、叶子节点。
- 让叶子节点承担召回，父块承担上下文回填。

### Step 3. 再迁移 sparse / hybrid

起点文件：

- [llamaindex_backend.py](/D:/AI应用/langchain-agent/backend/retrieval_core/llamaindex_backend.py)
- [lexical.py](/D:/AI应用/langchain-agent/backend/retrieval_core/lexical.py)

目标：

- 把 lexical 从长期正式角色降级为过渡 fallback。
- 引入 Qdrant 原生 sparse / hybrid。

### Step 4. 最后再收紧 benchmark 与 service

起点文件：

- [scifact_v2_eval.py](/D:/AI应用/langchain-agent/backend/tests/scifact_v2_eval.py)
- [service.py](/D:/AI应用/langchain-agent/backend/retrieval/service.py)

目标：

- benchmark 全量贴近正式链路。
- 服务层默认不再让旧入口长期共存。

---

## 5. 审查结论

当前系统最大的问题，不是“某个指标没调好”，而是：

- 正式解析契约还没锁死；
- 分层节点还没建起来；
- sparse/hybrid 还停留在过渡方案；
- benchmark 还没有完全贴近未来正式系统。

所以后面真正的推进顺序应该是：

`先修结构契约 -> 再建分层节点 -> 再迁移 sparse/hybrid -> 再收口 benchmark/service -> 再看 rerank 稳定收益`

在这个顺序之前继续调参数，收益不会稳定。
