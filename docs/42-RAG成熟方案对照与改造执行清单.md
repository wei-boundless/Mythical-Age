# RAG 成熟方案对照与改造执行清单

> 编写日期：2026-04-22  
> 目的：把外部成熟 RAG 流程与当前仓库现状逐项对照，形成一份可直接执行、可逐项验收、可持续推进直到达标的实施清单。  
> 适用范围：当前 `Docling + Normalized Ingestion + Qdrant/LlamaIndex v2 + rerank + SciFact/长场景测评` 链路。

---

## 1. 外部成熟方案的稳定主链

结合 LlamaIndex、Qdrant、Docling、BEIR/SciFact 等官方资料，成熟 RAG 一般遵循下面的执行顺序：

1. 结构化解析，而不是先把文档打散成裸文本。
2. 结构分块与分层节点，而不是全局单层固定粗切分。
3. 一阶段混合召回，dense 与 sparse 在同一最终返回粒度上融合。
4. 二阶段 rerank，只重排有限候选。
5. 父块或更大上下文回填，而不是把最终答案直接绑死在叶子小块。
6. 常态化评测与回归，不允许“感觉变好了”就算完成。

参考来源：

- Docling: <https://docling-project.github.io/docling/>
- LlamaIndex Hierarchical Node Parser: <https://developers.llamaindex.ai/python/framework-api-reference/node_parsers/hierarchical/>
- LlamaIndex Auto Merging Retriever: <https://developers.llamaindex.ai/python/framework-api-reference/retrievers/auto_merging/>
- LlamaIndex Recursive Retriever: <https://developers.llamaindex.ai/python/framework-api-reference/retrievers/recursive/>
- LlamaIndex Evaluation: <https://developers.llamaindex.ai/python/framework/module_guides/evaluating/>
- Qdrant Hybrid Search: <https://qdrant.tech/documentation/search/hybrid-queries/>
- Qdrant Text Search / Sparse: <https://qdrant.tech/documentation/guides/text-search/>
- Qdrant Reranking Hybrid Search: <https://qdrant.tech/documentation/advanced-tutorials/reranking-hybrid-search/>
- BEIR: <https://arxiv.org/abs/2104.08663>

---

## 2. 当前系统与成熟方案的核心差距

### 2.1 文档解析层

当前状态：

- 已经接入 `DoclingConverter`
- benchmark 也走正式 `NormalizedDocumentBuilder` 路径
- 但解析结果还没有形成稳定的“结构优先索引策略”

成熟方案要求：

- parser 输出的标题、段落、表格、页码、对象引用必须成为下游索引与召回的正式输入
- PDF / Markdown / 表格对象不能在进入索引前被压平成同质文本

当前差距：

- 结构元数据已生成，但还没有被完整转化为 dense/sparse 双侧的一等输入

### 2.2 分块层

当前状态：

- 正式系统以当前 Normalized Ingestion 产物为主
- 仍偏向单层块作为检索最小单元

成熟方案要求：

- 至少要有“父块 + 子块”两层
- 召回命中子块后，能够回到父块或文档级上下文

当前差距：

- 缺少正式的层级节点模型
- 命中后缺少 parent context merge / auto merge

### 2.3 混合检索层

当前状态：

- dense + 应用层 lexical 并存
- 之前已经暴露出 block 级 fusion 先于 doc 级合并的问题

成熟方案要求：

- dense 与 sparse 必须在同一个最终返回粒度上融合
- sparse 最好下沉到向量库原生能力，而不是长期维护自写伪 BM25

当前差距：

- lexical 还不是 Qdrant 原生 sparse
- hybrid 还没有迁到 Qdrant 原生 hybrid / RRF / DBSF

### 2.4 Rerank 层

当前状态：

- 已经有 rerank 接口
- 当前收益不稳定，且没有形成“只对有限高质量候选重排”的稳定收益曲线

成熟方案要求：

- rerank 只做第二阶段
- 候选必须先足够好，否则 rerank 只是放大坏召回

当前差距：

- 一阶段召回质量还不稳定
- rerank 还承担了部分不该由它承担的补救职责

### 2.5 评测层

当前状态：

- 已有 SciFact 脚本
- 已有长场景报告
- 已开始做 dense 健康检查与退化阻断

成熟方案要求：

- 评测必须拆开看 parser、chunk、dense、sparse、fusion、rerank
- 每阶段都要有可回归指标，而不是只看最终一份总分

当前差距：

- 还缺系统级诊断矩阵
- 还缺“坏点归因 -> 修复 -> 回归复核”的稳定闭环

---

## 3. 推荐目标架构

本仓库建议采用下面这条正式目标链路：

`Docling / MinerU -> 结构清洗 -> NormalizedDocument -> 分层节点 -> Qdrant dense + sparse -> Qdrant 原生 hybrid -> rerank -> parent context merge -> answer`

其中各层职责固定如下：

### 3.1 解析与清洗

- Docling 负责常规文档解析
- MinerU 负责 PDF 疑难场景补位
- 清洗层只负责结构修正、噪声剔除、字段标准化
- 清洗层不做 retrieval 特化刷分逻辑

### 3.2 分层节点

- 保留文档级、父块级、叶子块级的显式关系
- 叶子块用于召回
- 父块用于回填上下文
- 文档级用于 overview 型请求与最终归并

### 3.3 检索

- dense 负责语义召回
- sparse 负责关键词、实体词、公式词、缩写词命中
- hybrid 统一在最终返回粒度上做融合
- 不允许再出现“先块级融合、后文档合并”的流程

### 3.4 重排

- rerank 只接收 hybrid 召回候选
- rerank 不负责修 dense/sparse 没召回到的问题
- rerank 输出后再做必要的父块上下文扩展

### 3.5 评测

- SciFact/BEIR 用于检索准确率
- 仓库长场景用来验真实业务语义
- 二者都必须使用正式链路，不允许 benchmark 特化捷径

---

## 4. 分阶段执行清单

## Phase 0. 先锁执行边界

- [ ] 固定正式目标架构，不再接受临时 benchmark 特化分支进入主链
- [ ] 明确 dense、sparse、hybrid、rerank、parent-context 各自职责
- [ ] 明确最终返回粒度规则：`doc/page/object` 三类
- [ ] 明确 cutover 策略：旧 lexical 仅作过渡，不作为长期主方案
- [ ] 明确 rollback 策略：Qdrant sparse 未稳定前，允许回退到当前 lexical，但必须显式标记 degraded

完成标准：

- 所有后续代码改动都必须能映射到这五条边界之一

## Phase 1. 审查并收紧当前正式链路

- [ ] 审查 `backend/document_conversion/`，确认 Docling 与 MinerU 的职责边界
- [ ] 审查 `backend/normalized_ingestion/`，列出当前 block/object/document 的正式数据流
- [ ] 审查 `backend/retrieval_core/llamaindex_backend.py`，清理与正式链路冲突的临时逻辑
- [ ] 审查 `backend/retrieval/service.py`，确认 retrieval service 只走新系统，不残留旧入口
- [ ] 审查 benchmark 脚本，确认使用的就是正式 ingestion 和 retrieval 主链

完成标准：

- 当前系统的正式入口、正式索引流程、正式查询流程有唯一解释

## Phase 2. 重建结构清洗层

- [ ] 定义统一清洗输出字段：`title / section / page / object_ref / source_type / parser_backend / quality_flags`
- [ ] 区分“结构清洗”和“检索表达增强”，不把两者写成一个混合函数
- [ ] 为 Markdown / PDF / 表格对象统一输出标准化结构
- [ ] 为 PDF 场景定义 fallback：Docling 失败时走 MinerU
- [ ] 为清洗层增加质量标记，标记 OCR 异常、表格异常、顺序异常、标题缺失

完成标准：

- 任一文档进入 chunking 前，都能得到稳定、可检查、可追踪的结构化结果

重点文件：

- [docling_converter.py](/D:/AI应用/langchain-agent/backend/document_conversion/docling_converter.py)
- [builder.py](/D:/AI应用/langchain-agent/backend/normalized_ingestion/builder.py)
- [chunking.py](/D:/AI应用/langchain-agent/backend/normalized_ingestion/chunking.py)

## Phase 3. 把单层块升级为分层节点

- [ ] 设计文档级节点
- [ ] 设计父块级节点
- [ ] 设计叶子块级节点
- [ ] 明确 parent-child 引用关系与稳定 id 规则
- [ ] 调整索引构建，使 dense/sparse 至少基于叶子块建立
- [ ] 调整返回聚合，使命中叶子块后能回填父块摘要

完成标准：

- 检索命中和最终展示不再绑定在同一最小块对象上

重点文件：

- [models.py](/D:/AI应用/langchain-agent/backend/normalized_ingestion/models.py)
- [chunking.py](/D:/AI应用/langchain-agent/backend/normalized_ingestion/chunking.py)
- [llamaindex_backend.py](/D:/AI应用/langchain-agent/backend/retrieval_core/llamaindex_backend.py)

## Phase 4. 迁移 sparse 检索到正式方案

- [ ] 审查当前应用层 lexical index 是否还承担正式召回职责
- [ ] 定义 Qdrant sparse collection / vector schema
- [ ] 接入 Qdrant 原生 sparse/BM25
- [ ] 验证实体词、缩写词、医学术语、数字词命中是否优于当前自写 lexical
- [ ] 保留当前 lexical 作为过渡 fallback，但加显式状态标记

完成标准：

- sparse 检索由正式底座承担，不再长期依赖应用层伪 BM25

重点文件：

- [lexical.py](/D:/AI应用/langchain-agent/backend/retrieval_core/lexical.py)
- [llamaindex_backend.py](/D:/AI应用/langchain-agent/backend/retrieval_core/llamaindex_backend.py)

## Phase 5. 重建 hybrid 融合

- [ ] 融合统一发生在最终返回粒度上
- [ ] dense/sparse 先各自聚合，再融合
- [ ] 引入正式融合策略，优先考虑 Qdrant 原生 `rrf` 或 `dbsf`
- [ ] 保留每一路 score breakdown，便于诊断
- [ ] 为 `semantic_lookup / page_grounded_lookup / table_lookup / document_overview` 定义稳定融合粒度

完成标准：

- hybrid top1 必须实际优于 lexical-only，而不是只在 rank 指标上看起来更平滑

重点文件：

- [llamaindex_backend.py](/D:/AI应用/langchain-agent/backend/retrieval_core/llamaindex_backend.py)
- [service.py](/D:/AI应用/langchain-agent/backend/retrieval/service.py)

## Phase 6. 重建 rerank 策略

- [ ] 明确 rerank 输入候选规模
- [ ] 验证当前 heuristic reranker 是否仅作 fallback
- [ ] 接入正式 cross-encoder 或等价 reranker
- [ ] 对比 `no-rerank / heuristic / model-rerank` 三组结果
- [ ] 控制 rerank 延迟上限，防止它拖垮正式入口

完成标准：

- rerank 能稳定抬升 top1 / mrr，而不是偶然补救

重点文件：

- [reranker.py](/D:/AI应用/langchain-agent/backend/RAG/reranker.py)
- [service.py](/D:/AI应用/langchain-agent/backend/retrieval/service.py)

## Phase 7. 建立父块上下文回填

- [ ] 命中叶子块后，返回父块或相邻证据摘要
- [ ] 控制回填长度，避免把大段无关文本重新塞回去
- [ ] 对文档 overview 请求直接走文档级聚合
- [ ] 对 page grounded 请求保持页级定位
- [ ] 对 object/table 请求保持对象粒度不丢

完成标准：

- 返回结果既保留精确命中，又具备足够解释上下文

## Phase 8. 重建评测与回归矩阵

- [ ] SciFact 拆分评测 `dense / sparse / hybrid / rerank`
- [ ] 为每次重建输出 index health 报告
- [ ] 为每次重建输出 retrieval diagnostics
- [ ] 长场景测评与 SciFact 同时保留
- [ ] 建立固定回归阈值，不达标不得宣布完成

建议阈值：

- [ ] hybrid `accuracy@1` 必须显著高于 sparse-only
- [ ] rerank 后 `mrr@10` 必须稳定提升
- [ ] 同一配置重复跑，波动必须在可接受范围
- [ ] dense health 必须为 `ready`

重点文件：

- [scifact_v2_eval.py](/D:/AI应用/langchain-agent/backend/tests/scifact_v2_eval.py)
- [report.md](/D:/AI应用/langchain-agent/output/test_runs/20260421-212111-long/report.md)

---

## 5. 文件级执行清单

### 5.1 文档解析与清洗

- [ ] [docling_converter.py](/D:/AI应用/langchain-agent/backend/document_conversion/docling_converter.py)
- [ ] [builder.py](/D:/AI应用/langchain-agent/backend/normalized_ingestion/builder.py)
- [ ] [chunking.py](/D:/AI应用/langchain-agent/backend/normalized_ingestion/chunking.py)
- [ ] [models.py](/D:/AI应用/langchain-agent/backend/normalized_ingestion/models.py)

### 5.2 检索与索引

- [ ] [llamaindex_backend.py](/D:/AI应用/langchain-agent/backend/retrieval_core/llamaindex_backend.py)
- [ ] [lexical.py](/D:/AI应用/langchain-agent/backend/retrieval_core/lexical.py)
- [ ] [service.py](/D:/AI应用/langchain-agent/backend/retrieval/service.py)
- [ ] [models.py](/D:/AI应用/langchain-agent/backend/RAG/models.py)

### 5.3 Rerank 与查询层

- [ ] [reranker.py](/D:/AI应用/langchain-agent/backend/RAG/reranker.py)
- [ ] [query_rewriter.py](/D:/AI应用/langchain-agent/backend/RAG/query_rewriter.py)
- [ ] [router.py](/D:/AI应用/langchain-agent/backend/RAG/router.py)

### 5.4 评测与回归

- [ ] [scifact_v2_eval.py](/D:/AI应用/langchain-agent/backend/tests/scifact_v2_eval.py)
- [ ] [retrieval_core_phase2_regression.py](/D:/AI应用/langchain-agent/backend/tests/retrieval_core_phase2_regression.py)
- [ ] [39-长场景语义问题追踪清单-20260421-212111.md](/D:/AI应用/langchain-agent/docs/39-长场景语义问题追踪清单-20260421-212111.md)
- [ ] [41-RAG检索持续修复与稳定达标计划书.md](/D:/AI应用/langchain-agent/docs/41-RAG检索持续修复与稳定达标计划书.md)

---

## 6. 执行中的禁区

- [ ] 不允许为 SciFact 临时加一套与正式系统不同的切分逻辑
- [ ] 不允许为 benchmark 人工拼接 query 特化字段去刷分
- [ ] 不允许 dense 不健康时继续把结果当作 hybrid 结果汇报
- [ ] 不允许把 rerank 当作召回失败的主要补丁
- [ ] 不允许在主链长期保留旧 lexical 与新 sparse 的双重正式职责
- [ ] 不允许在没有回归验证的情况下宣布“已完成重建”

---

## 7. 完成判定

只有同时满足下面条件，才允许认为本轮改造完成：

- [ ] 正式链路已经切到结构清洗 + 分层节点 + 正式 sparse/hybrid
- [ ] hybrid 指标相对 sparse-only 有稳定提升
- [ ] rerank 有稳定正收益
- [ ] SciFact 重复评测结果稳定
- [ ] 长场景语义问题至少完成一轮回归复核
- [ ] 所有关键路径不再依赖旧链路兜底

如果以上任一项未满足，则继续推进，不得以“先这样用着”作为结束条件。
