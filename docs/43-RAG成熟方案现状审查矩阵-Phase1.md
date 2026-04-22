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
- 分层节点层：`部分符合`
- sparse / lexical 检索层：`部分符合`
- hybrid 融合层：`部分符合`
- rerank 层：`部分符合`
- 服务切换与旧入口治理：`部分符合`
- benchmark 与回归层：`部分符合`

核心结论：

1. 当前链路已经具备“正式解析 -> normalized ingestion -> 检索”的基础骨架。
2. 检索主链已经进入 `qdrant dense + qdrant sparse + qdrant native rrf + lexical fallback` 阶段，但 hybrid 诊断与评测闭环还没完全收口。
3. 父块/子块分层节点体系已经进入正式链路，但 benchmark 和后续评测还没有完全围绕三层节点做验收闭环。
4. benchmark 虽然已经接入 dense health 检查，但仍没有完全走正式解析能力。
5. “结构约束下的动态分块”正式规则已经落到代码，但还需要继续压实 benchmark 与正式评测的一致性。
6. 现阶段最优先的实施起点已经从“先建结构骨架”转到“继续完成 sparse/hybrid 正式化与评测闭环”。

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
- builder 还没有承担“结构约束下的动态分块输入契约”收口职责。
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
- 已能稳定承载 `document_summary / parent_section / leaf_block` 三层节点所需字段。

不符合点：

- 三层节点虽然已进入运行链路，但模型边界与 benchmark 验收标准还没有完全收紧。
- 句子级“不入主索引”的边界已在实现上遵守，但还需要持续通过评测入口验证没有被旁路破坏。

判断：

- 数据模型已经完成从“字段预留”到“正式运行”的第一轮升级，但仍需继续压实验收与边界治理。

## 2.4 Chunking / Indexable Units

文件：

- [chunking.py](/D:/AI应用/langchain-agent/backend/normalized_ingestion/chunking.py)

状态：

- `部分符合`

已符合点：

- 已能生成 `document_summary / parent_section / leaf_block` 三层正式节点。
- 已能保留 `content_block / object_block / page_summary` 等下游所需的结构语义。
- 已将 title / section / parser_backend 等元数据送入 unit metadata。
- 已落地结构优先、长度受控的动态分块规则。

不符合点：

- 当前三层节点虽然可生成，但 benchmark 与真实评测还没有完全验证其收益稳定。
- 句子级局部增强、父块回填和最终展示之间的边界还需要继续通过服务层和评测层压实。

判断：

- 这里已经不再是“结构缺口”，而是“结构能力已落地，但收益闭环还未完全形成”。

## 2.5 Retrieval Backend

文件：

- [llamaindex_backend.py](/D:/AI应用/langchain-agent/backend/retrieval_core/llamaindex_backend.py)

状态：

- `部分符合`

已符合点：

- dense 构建、持久化、健康检查已经进入正式后端。
- retrieval 已支持 `semantic_lookup / page_grounded_lookup / table_lookup / document_overview` 四类模式。
- 有聚合、融合、breakdown 这些观测基础。
- 已切到 `dense coalesce -> sparse coalesce -> fuse` 的顺序。
- 已接上 `parent_context / document_context` 回填。
- 已打通 Qdrant named dense + sparse vectors，且 sparse 查询已可直接命中。
- 已接上 Qdrant 原生 `prefetch + FusionQuery(RRF)` 作为 hybrid 主路径。
- 已显式固化四类 query mode 的最终返回粒度规则，并把 `result_granularity` 写入结果元数据。
- 已为 native hybrid / dense / sparse / lexical fallback 保留可诊断的 `score_breakdown`。

不符合点：

- lexical fallback 仍存在，说明 sparse/hybrid 还没有完全脱离应用层降级路径。
- 当前仍保留应用层手工 fusion 作为 native hybrid 失败时的退化路径。
- benchmark 还没有证明 hybrid top1 能稳定优于 lexical-only。

判断：

- 当前偏差已从“主链方向错误”缩小为“native hybrid 已接通且诊断增强完成，但收益闭环与降级治理还未完全收口”。

## 2.6 Lexical / Sparse 层

文件：

- [lexical.py](/D:/AI应用/langchain-agent/backend/retrieval_core/lexical.py)

状态：

- `部分符合`

已符合点：

- tokenization 已比最早版本更干净。
- `build_searchable_text()` 已开始注入 title / section / header。
- 已提供 `term_ids / idf / sparse payload`，可为 Qdrant sparse vector 提供正式输入。

不符合点：

- 仍保留应用层 lexical fallback。
- 同一文件里仍混有 fallback 检索与过渡期评分逻辑，职责仍偏厚。
- 当前 sparse 已可入 Qdrant，但 hybrid 还未完全切到库内融合。

判断：

- 该模块已经从“正式 sparse 主职责”降到“Qdrant sparse 的供料层 + fallback 兼容层”，但还需要继续瘦身。

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

- benchmark 现在虽然已改为走公共 structured-text conversion helper，但仍不是正式 Docling/MinerU 解析入口。
- 这意味着 benchmark 还没有完整覆盖“正式解析 -> 正式清洗 -> 正式索引”的全链路。

判断：

- benchmark 已经比之前健康很多，但还不算完全贴近未来正式系统。

---

## 3. 规则映射矩阵

为避免后续实施时反复在 [42-RAG成熟方案对照与改造执行清单.md](/D:/AI应用/langchain-agent/docs/42-RAG成熟方案对照与改造执行清单.md) 与本审查文档之间来回跳转，这里把当前核心模块直接映射到新规则。

### 3.1 规则定义

- `R1 结构契约先于检索`
  解析结果必须先形成稳定结构契约，再进入切分、索引和召回。
- `R2 结构约束下的动态分块`
  切分必须结构优先、长度受控，禁止纯固定粗切分和启发式主导切分。
- `R3 三层节点主链`
  正式主链优先采用 `document / parent-section / leaf-block` 三层。
- `R4 sparse/hybrid 正式化`
  sparse 不再长期依赖应用层伪 BM25，hybrid 必须在最终返回粒度上融合。
- `R5 rerank 只做第二阶段`
  rerank 不能承担一阶段召回失败的主补丁职责。
- `R6 benchmark 必须贴近正式链路`
  benchmark 不允许绕开正式解析、清洗、切分、索引主链。
- `R7 旧入口必须退出正式控制面`
  旧链路只能短期 shadow，不应长期与新链路并列为正式主路径。

### 3.2 模块到规则映射

| 模块 | 当前状态 | 触犯/缺失规则 | 直接问题 |
| --- | --- | --- | --- |
| `docling_converter.py` | 部分符合 | `R1` `R2` | 有解析入口，但结构契约与后续分块输入还没锁死 |
| `builder.py` | 部分符合 | `R1` `R2` `R3` | 只做标准化，还没成为动态分块与层级节点收口点 |
| `normalized_ingestion/models.py` | 部分符合 | `R3` | 三层节点已进入运行链路，但模型边界与验收标准仍需压实 |
| `chunking.py` | 部分符合 | `R2` `R3` | 已有结构约束动态分块和三层节点，但收益闭环尚未完全跑通 |
| `llamaindex_backend.py` | 部分符合 | `R4` | 已接 Qdrant sparse + native RRF，但降级路径和评测闭环仍未完全收口 |
| `lexical.py` | 部分符合 | `R4` | 已退为供料层 + fallback，但仍未完全瘦身 |
| `service.py` | 部分符合 | `R5` `R7` | 新链路已接入，但旧入口仍在正式服务控制面里共存 |
| `scifact_v2_eval.py` | 部分符合 | `R6` | benchmark 健康检查有了，但仍没有完全走正式解析能力 |

### 3.3 当前最缺的不是哪一个文件，而是哪三条规则

当前最需要继续压实的不是单个函数，而是下面三条规则还没完全闭环：

1. `R4 sparse/hybrid 正式化`
2. `R6 benchmark 必须贴近正式链路`
3. `R7 旧入口必须退出正式控制面`

这三条不闭环，后续 rerank、评测、调参都仍然会被底层不稳定拖累。

---

## 4. 当前最关键的坏点排序

按对目标方案的破坏程度排序，当前最该优先解决的是：

1. native hybrid 的收益还没有在正式 benchmark 链路里被稳定证明。
2. `scifact_v2_eval` 还没有完全走正式解析能力。
3. `retrieval service` 仍保留旧入口切换分支。
4. `lexical.py` 仍保留过厚的 fallback 与过渡职责。
5. `docling_converter` 的结构输出契约还不够刚性。
6. 三层节点收益还没有在正式评测链路中被压实证明。

---

## 5. 模块动作表

这一节只回答一个问题：每个关键模块下一步到底要做什么，做完应该交付什么产物。

### 5.1 `docling_converter.py`

- 当前问题：
  解析顺序有了，但结构契约和后续动态分块输入还不够刚性。
- 下一步动作：
  固定 `title / section / page / object_ref / parser_backend / fallback_used / parser_route / quality_flags`。
- 完成产物：
  稳定 `ConversionResult / ConversionBlock` 契约，供 builder 和 chunking 直接消费。

### 5.2 `builder.py`

- 当前问题：
  只做标准化，没有把结构输入真正收口成后续分块/建模的正式起点。
- 下一步动作：
  让 builder 成为结构契约收口点，并输出动态分块可直接使用的字段。
- 完成产物：
  稳定 `NormalizedDocument / NormalizedBlock / NormalizedObjectRef` 输入层。

### 5.3 `normalized_ingestion/models.py`

- 当前问题：
  只有字段预留，没有正式三层节点模型。
- 下一步动作：
  定义文档节点、父块节点、叶子节点，以及它们的关系句柄。
- 完成产物：
  明确的三层节点数据模型和稳定 id / parent-child 引用规则。

### 5.4 `chunking.py`

- 当前问题：
  仍是单层 indexable unit 生成器。
- 下一步动作：
  引入“结构约束下的动态分块”，并按三层节点生成 indexable units。
- 完成产物：
  `document / parent-section / leaf-block` 三层 unit 生成逻辑，以及句子级只作局部增强的边界。

### 5.5 `llamaindex_backend.py`

- 当前问题：
  还建立在应用层 lexical 与手工 fusion 上。
- 下一步动作：
  先适配三层节点与父块回填，再迁移 sparse/hybrid 到正式方案。
- 完成产物：
  基于叶子召回、父块回填、最终粒度融合的新检索主链。

### 5.6 `lexical.py`

- 当前问题：
  当前还在承担正式 sparse 主职责。
- 下一步动作：
  降级为过渡 fallback 或局部兼容层。
- 完成产物：
  sparse 正式职责转移后，仅保留必要兼容能力。

### 5.7 `service.py`

- 当前问题：
  旧入口仍保留在正式控制面里。
- 下一步动作：
  随主链稳定逐步压缩 `legacy_only / shadow_read` 的正式存在。
- 完成产物：
  默认只读新系统，旧链路只作短期 shadow 或回滚保障。

### 5.8 `scifact_v2_eval.py`

- 当前问题：
  benchmark 还没有完全贴近正式解析主链。
- 下一步动作：
  把 benchmark 全量贴到正式解析、动态分块、分层节点、正式 hybrid 主链。
- 完成产物：
  可用于真实回归的正式评测入口，而不是“近似正式链路”的诊断入口。

---

## 6. 下一阶段的正式实施起点

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
- 明确后续动态分块可使用的结构字段，不再让切分层临时猜测。

### Step 2. 先锁结构约束下的动态分块规则

起点文件：

- [docling_converter.py](/D:/AI应用/langchain-agent/backend/document_conversion/docling_converter.py)
- [builder.py](/D:/AI应用/langchain-agent/backend/normalized_ingestion/builder.py)
- [chunking.py](/D:/AI应用/langchain-agent/backend/normalized_ingestion/chunking.py)

目标：

- 明确结构边界优先，长度控制其次。
- 明确允许参与切分的信号：标题、段落、列表项、表格行、标点停顿。
- 明确禁止作为主规则的启发式：纯 `TextRank`、纯固定 token 粗切分。

### Step 3. 再把单层 block 升级为分层节点

起点文件：

- [models.py](/D:/AI应用/langchain-agent/backend/normalized_ingestion/models.py)
- [chunking.py](/D:/AI应用/langchain-agent/backend/normalized_ingestion/chunking.py)

目标：

- 正式定义文档节点、父块节点、叶子节点。
- 让叶子节点承担召回，父块承担上下文回填。
- 把句子级能力限定在局部增强层，不作为第一阶段全量主索引。

### Step 4. 再迁移 sparse / hybrid

起点文件：

- [llamaindex_backend.py](/D:/AI应用/langchain-agent/backend/retrieval_core/llamaindex_backend.py)
- [lexical.py](/D:/AI应用/langchain-agent/backend/retrieval_core/lexical.py)

目标：

- 把 lexical 从长期正式角色降级为过渡 fallback。
- 引入 Qdrant 原生 sparse / hybrid。

### Step 5. 最后再收紧 benchmark 与 service

起点文件：

- [scifact_v2_eval.py](/D:/AI应用/langchain-agent/backend/tests/scifact_v2_eval.py)
- [service.py](/D:/AI应用/langchain-agent/backend/retrieval/service.py)

目标：

- benchmark 全量贴近正式链路。
- 服务层默认不再让旧入口长期共存。

---

## 7. 审查结论

当前系统最大的问题，不是“某个指标没调好”，而是：

- 正式解析契约还没锁死；
- 动态分块规则还没锁死；
- 分层节点还没建起来；
- sparse/hybrid 还停留在过渡方案；
- benchmark 还没有完全贴近未来正式系统。

所以后面真正的推进顺序应该是：

`先修结构契约 -> 再锁动态分块规则 -> 再建分层节点 -> 再迁移 sparse/hybrid -> 再收口 benchmark/service -> 再看 rerank 稳定收益`

在这个顺序之前继续调参数，收益不会稳定。
