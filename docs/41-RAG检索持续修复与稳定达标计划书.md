# RAG 检索持续修复与稳定达标计划书

> 编写日期：2026-04-22  
> 目标：针对当前 Docling + Normalized Ingestion + Qdrant/LlamaIndex v2 检索链路中“dense 索引未真正建成、系统静默退化为 lexical-only、SciFact 测评结果失真且准确率下滑”的问题，先完成代码与框架审查，锁定坏点；再基于成熟方案设计修复路线；随后进入“修复一次、验证一次、失败继续修复”的持续工作闭环，直到在测试集上得到稳定且可重复的准确结果后才允许退出。

---

## Part A. 技术报告

## 1. 目的

本计划书要解决的不是单一参数问题，而是当前 RAG v2 链路的三个系统级缺陷：

1. dense 检索可用性没有被构建流程真实保证；
2. lexical 表达与 tokenization 对 SciFact 这类 claim retrieval 场景不够稳；
3. 当前 benchmark 结果混入了“dense 已掉线”的退化状态，导致测评结论本身不可信。

本计划书覆盖的范围包括：

- dense 构建、持久化、重开校验、查询可用性
- lexical 索引文本表达、tokenization、融合逻辑
- benchmark 与回归验证链路
- 直到测评达标前的持续修复执行规则

本计划书不覆盖：

- 主线程 follow-up / binding / canonical answer 设计
- 与本次 dense / lexical 问题无关的 memory、continuation、output boundary 改造

---

## 2. 当前断裂点与真实坏因

## 2.1 现象层

当前在 SciFact benchmark 上观察到的症状是：

- 正式链路切分后，`accuracy@1` 从旧 benchmark 的 `0.54` 降到 `0.48`
- `rewrite` 几乎不介入，`rerank` 只有极小提升
- 将 `candidate_top_k` 从 `10` 提到 `30`、`100`，结果仍基本不变
- 部分失败 query 的 gold 文档连 `top100` 都没有进入

表面上看像是“切分变细后召回变差”，但进一步审查后发现这只是表象。

## 2.2 代码审查后确认的坏点

### 坏点 A. dense 索引元数据与真实可用性脱节

当前 `benchmark/meta.json` 声称 dense 已经 `ready`，并记录：

- `dense_documents = 16100`
- `qdrant_collection = agent__benchmark`

但实际在 benchmark dense 路径下重新打开本地 Qdrant 时，`collections = []`，dense 查询直接返回空。

相关代码：

- [llamaindex_backend.py](/D:/AI应用/langchain-agent/backend/retrieval_core/llamaindex_backend.py)
- [meta.json](/D:/AI应用/langchain-agent/output/benchmark_runtime/scifact_v2/storage/indexes_v2/benchmark/meta.json)
- [dense/meta.json](/D:/AI应用/langchain-agent/output/benchmark_runtime/scifact_v2/storage/indexes_v2/benchmark/dense/meta.json)

直接后果：

- `_retrieve_dense_qdrant()` 在 collection 不存在时直接返回空
- 上层不报错，继续 lexical 检索
- benchmark 实际在测“lexical-only 退化态”，不是完整 hybrid

### 坏点 B. dense 失效被静默吞掉，系统没有 fail-fast

当前 dense 查询路径：

- collection 不存在时返回 `[]`
- query_vector 为空时返回 `[]`

没有进入显式错误、状态降级标记、或 build invalidation。

这意味着：

- dense 掉线不会阻止系统继续工作
- 但会把准确率问题伪装成“召回差”或“切分差”
- benchmark 会得出误导性结论

### 坏点 C. lexical 索引只吃 `unit.text`，没有使用更强的 searchable text

当前 lexical 索引构建逻辑直接使用：

- `build_lexical_index_payload([unit.text for unit in units])`

而没有使用已经存在的 richer text 组装思路，例如标题、section、header、正文联合表达。

直接后果：

- 标题和正文证据被拆散
- SciFact 这种“标题给主题、正文给 claim 证据”的数据更容易掉分
- heading / paragraph 作为独立 unit 参与 BM25，表达强度偏弱

### 坏点 D. lexical tokenizer 对生物医学 claim 检索不稳

当前 tokenizer 会保留带尾部标点的 token，例如：

- `PGE2.` 被当成 `pge2.`
- `homocysteine.` 被当成 `homocysteine.`

而 gold 文档里可能对应：

- `E2`
- `homocysteine`

这会造成：

- 精确医学词错配
- 高频泛词如 `aspirin / vitamin / production / levels` 反而主导排序
- dense 一旦失效，BM25 噪声被迅速放大

### 坏点 E. benchmark 结果当前不具备“是否修好 dense”的判别力

现有 benchmark 脚本可以输出最终指标，但没有把以下状态列为硬门槛：

- dense collection 是否真实存在
- dense 查询是否能返回候选
- dense / lexical / fusion 各路候选占比
- benchmark 是否在 lexical-only 退化态下运行

这导致：

- 即使 dense 已坏，benchmark 仍能跑完
- 结果文件看似完整，但不能代表系统已建好

---

## 3. 依据来源

## 3.1 本地设计原则与既有计划

本次计划服从以下本地文档中的既有原则：

- [38-去启发式续接与显式句柄主链重构技术报告及计划书.md](/D:/AI应用/langchain-agent/docs/38-去启发式续接与显式句柄主链重构技术报告及计划书.md)
- [40-Docling与LlamaIndex版前处理和RAG重建计划书.md](/D:/AI应用/langchain-agent/docs/40-Docling与LlamaIndex版前处理和RAG重建计划书.md)

从这些文档提炼出的约束：

1. 不用 benchmark 特化的突兀结构去“刷分”。
2. 修结构，不修表象。
3. steady-state 查询不应依赖临时全量重建。
4. 元数据、运行状态、检索结果必须一致，不能“文件上 ready，运行时不可用”。
5. 必须把执行顺序先锁死，再实施。

## 3.2 当前代码审查范围

本次确认坏点时重点审查了这些模块：

- [backend/retrieval_core/llamaindex_backend.py](/D:/AI应用/langchain-agent/backend/retrieval_core/llamaindex_backend.py)
- [backend/retrieval_core/lexical.py](/D:/AI应用/langchain-agent/backend/retrieval_core/lexical.py)
- [backend/tests/scifact_v2_eval.py](/D:/AI应用/langchain-agent/backend/tests/scifact_v2_eval.py)
- [backend/embedding_compat.py](/D:/AI应用/langchain-agent/backend/embedding_compat.py)
- [backend/document_conversion/docling_converter.py](/D:/AI应用/langchain-agent/backend/document_conversion/docling_converter.py)
- [backend/normalized_ingestion/builder.py](/D:/AI应用/langchain-agent/backend/normalized_ingestion/builder.py)
- [backend/normalized_ingestion/chunking.py](/D:/AI应用/langchain-agent/backend/normalized_ingestion/chunking.py)
- [backend/normalized_ingestion/eligibility.py](/D:/AI应用/langchain-agent/backend/normalized_ingestion/eligibility.py)

## 3.3 外部成熟方案依据

本次修复方案借鉴以下成熟方案中的“可借鉴机制”，而不是整体照抄：

### Qdrant

- Qdrant 官方文档与客户端文档强调 collection 是可显式管理、可显式校验的持久化对象，不能把“写入过点数据”当成“collection 已可用”。
- 参考：
  - https://qdrant.tech/documentation/
  - https://github.com/qdrant/qdrant-client

本项目借鉴点：

- build 完成后必须 reopen 并验证 collection
- collection 不可用时不能静默算作 `ready`
- hybrid 检索的前提是 dense 与 lexical 两侧都是真可用，不是纸面可用

### LlamaIndex

- LlamaIndex 官方文档提供了更成熟的 BM25 retriever、fusion retriever 和 retrieval composition 思路。
- 参考：
  - https://docs.llamaindex.ai/en/stable/examples/retrievers/bm25_retriever/
  - https://docs.llamaindex.ai/en/stable/examples/retrievers/relative_score_dist_fusion/
  - https://docs.llamaindex.ai/en/stable/examples/retrievers/reciprocal_rerank_fusion/

本项目借鉴点：

- 候选生成和最终返回数量分离
- dense / lexical / fusion 结果分层可观测
- 不把融合结果当作黑盒，保留每一路的 breakdown

### BEIR / SciFact benchmark 实践

- BEIR 类 benchmark 的核心价值在于统一语料、统一 qrels、可重复评估，而不是在 benchmark 中塞项目特化捷径。
- 参考：
  - https://github.com/beir-cellar/beir

本项目借鉴点：

- benchmark 必须尽量贴近正式链路
- benchmark 可以有观测增强，但不能有结构特化捷径
- 结果必须可重复，并能解释为什么变好或变坏

---

## 4. 方案取舍

## 4.1 备选方案 A. 继续只调 benchmark 参数

内容：

- 调 `candidate_top_k`
- 调 fusion 权重
- 调 rerank top_n

优点：

- 快

缺点：

- 当前 dense 已失效，调参是在坏基础上微调
- 不能解决“纸面 ready、实际不可用”
- 会继续污染判断

结论：

- 不采用

## 4.2 备选方案 B. 立刻整体重写成 Qdrant 原生 hybrid / sparse vector

内容：

- 直接大改 dense + sparse + fusion 全链路

优点：

- 理论上上限更高

缺点：

- 当前连最基本的 dense availability 都还没验证闭环
- 在坏基线之上再做大迁移，定位成本会急剧升高
- 会把“修可用性”和“换架构”混在一起

结论：

- 本轮不采用
- 作为后续增强路线保留

## 4.3 备选方案 C. 先修正确性与可观测性，再修 lexical 表达，再做准确率迭代

内容：

1. 先修 dense build-read-verify 闭环
2. 再修 lexical 文本表达和 tokenizer
3. 再修 fusion / candidate / rerank
4. 每一轮都重跑 benchmark

优点：

- 能清晰区分“没建好”和“建好了但效果还差”
- 更符合当前代码基础
- 更适合持续迭代直到达标

缺点：

- 前两轮可能先看到“正确性恢复”，不一定立刻看到大幅涨分

结论：

- 采用

---

## 5. 推荐设计方向

本次采用的目标设计不是“再造一套新 RAG”，而是给当前 v2 链路加上严格的持续修复闭环。

核心方向如下：

1. dense availability 成为第一真相  
   只要 dense collection 不可 reopen、不可 query、不可返回候选，就不允许把当前索引标成 `ready`。

2. benchmark 先验证链路有效，再验证指标  
   benchmark 必须先证明当前不是 lexical-only 退化态，然后才允许讨论准确率。

3. lexical 表达从“原始块文本”升级为“结构化 searchable text”  
   至少把标题、section、正文进行可控拼接，避免 heading / paragraph 证据被拆散。

4. tokenization 从“粗暴保留标点”升级为“检索友好规范化”  
   先修标点、大小写、常见医学词边界问题，再考虑后续专业词表增强。

5. 每轮修复只做一个主因改动，然后立即重建、复测、比较  
   不允许多项主因同时改动后再猜是哪项有效。

---

## 5A. 固定执行流

本次持续修复按以下固定顺序推进：

### Stage 0. 审计冻结

输入：

- 当前 v2 检索代码
- 当前 benchmark 结果

输出：

- 坏点报告
- 冻结的基线指标

禁止：

- 在未完成坏点确认前先改 tokenizer、rerank、切分

### Stage 1. dense 可用性修复

输入：

- dense build 代码
- Qdrant 持久化目录

输出：

- build-read-verify 闭环
- dense availability smoke test

禁止：

- 用 lexical 结果掩盖 dense 失效
- dense 不可用却继续写 `ready`

### Stage 2. benchmark 可信度修复

输入：

- dense availability
- benchmark 脚本

输出：

- benchmark 前置健康检查
- dense / lexical / fusion observability

禁止：

- benchmark 继续在 lexical-only 状态下输出“完整成功结果”

### Stage 3. lexical 表达修复

输入：

- 当前 indexable units
- 当前 lexical 索引构建逻辑

输出：

- searchable text 方案
- tokenizer 修正

禁止：

- 添加 benchmark 专用分支
- 脱离正式链路另做一套 SciFact 特化切分

### Stage 4. fusion / candidate / rerank 修复

输入：

- dense 与 lexical 均可用的真实候选集

输出：

- 候选深度与最终返回解耦
- fusion 细化
- rerank 接入验证

禁止：

- 在 dense 不可用时先调 fusion 权重

### Stage 5. 持续迭代直到达标

输入：

- 每轮修复后的 benchmark 结果

输出：

- 连续稳定达标的结果
- 最终清理清单

禁止：

- 指标偶然一次达标就立即结束
- 没有稳定性复测就宣告完成

---

## 6. 数据与协议调整

## 6.1 新增运行状态字段

需要新增或固化以下状态：

- `dense_status`: `missing | building | invalid | ready`
- `dense_verified_at`
- `dense_verified_query_smoke`
- `benchmark_mode`: `invalid | lexical_only | dense_only | hybrid_ready`

## 6.2 benchmark 输出协议增强

benchmark 结果文件必须新增：

- dense top_k 命中数量
- lexical top_k 命中数量
- fusion 前后候选数量
- dense 是否真实返回
- 当前结果是否允许计入正式评估

## 6.3 searchable text 协议

lexical 索引不再只吃裸 `unit.text`，而是统一生成：

- `searchable_text = title + section_path + header + body`

拼接规则要固定，不允许 benchmark 特化。

---

## 6A. 先行锁定的工程决定

为防止实现过程再次跑偏，先固定以下决定：

1. 不恢复旧 benchmark 特化粗切分逻辑。
2. 不增加“仅 SciFact 使用”的专用 chunking。
3. 不在 dense 未修好前继续调 rerank 作为主方案。
4. benchmark 入口继续使用正式链路风格的 `DoclingConverter -> NormalizedDocumentBuilder -> build_indexable_units`。
5. 若本地 Qdrant path 模式持续不稳定，则允许切换到显式 Qdrant server 模式，但必须先完成验证报告后再切换。

---

## 7. 模块级修复计划

## 7.1 Dense 构建与读取层

涉及：

- [backend/retrieval_core/llamaindex_backend.py](/D:/AI应用/langchain-agent/backend/retrieval_core/llamaindex_backend.py)

动作：

- build 后立即 reopen collection 校验
- `meta.json` 以“验证结果”为准，不以“upsert 成功”为准
- dense retrieval 空结果要区分：
  - collection 不存在
  - query_vector 为空
  - query 成功但 0 命中

## 7.2 Lexical 索引与 tokenizer

涉及：

- [backend/retrieval_core/lexical.py](/D:/AI应用/langchain-agent/backend/retrieval_core/lexical.py)
- [backend/retrieval_core/llamaindex_backend.py](/D:/AI应用/langchain-agent/backend/retrieval_core/llamaindex_backend.py)

动作：

- 用 `build_searchable_text` 方向重构 lexical 输入文本
- 修正 tokenizer 中标点黏连问题
- 保留最小必要停用词策略，不做大规模词表硬编码

## 7.3 Benchmark 与观测

涉及：

- [backend/tests/scifact_v2_eval.py](/D:/AI应用/langchain-agent/backend/tests/scifact_v2_eval.py)

动作：

- 增加 dense/lexical/fusion observability
- 增加 benchmark preflight
- 将 benchmark 结果分成：
  - chain health
  - retrieval quality
  - rerank delta

## 7.4 文档转换与标准化层

涉及：

- [backend/document_conversion/docling_converter.py](/D:/AI应用/langchain-agent/backend/document_conversion/docling_converter.py)
- [backend/normalized_ingestion/builder.py](/D:/AI应用/langchain-agent/backend/normalized_ingestion/builder.py)
- [backend/normalized_ingestion/chunking.py](/D:/AI应用/langchain-agent/backend/normalized_ingestion/chunking.py)
- [backend/normalized_ingestion/eligibility.py](/D:/AI应用/langchain-agent/backend/normalized_ingestion/eligibility.py)

动作：

- 这一层本轮不重做结构
- 只做“必要观测补强”，用于解释 lexical/dense 失配

---

## 8. 阶段计划

## Phase 1. 先修“索引到底建没建好”

目标：

- 让 dense availability 成为可验证真相

影响文件：

- `backend/retrieval_core/llamaindex_backend.py`
- `backend/tests/scifact_v2_eval.py`

完成标准：

- benchmark collection 可 reopen
- dense query 对 sanity query 不再全部返回 0
- dense 不可用时 build/status 明确失败

回滚条件：

- 如修改后 benchmark collection 全面不可读，则回滚该阶段实现并保留日志

禁止：

- 在本阶段同时修改 tokenizer 和 rerank

## Phase 2. 修 benchmark 可信度

目标：

- benchmark 不再掩盖 dense 失效

完成标准：

- 结果文件能清楚显示当前是 `hybrid_ready` 还是 `lexical_only`
- dense 失效时 benchmark 明确标红

禁止：

- 继续输出“指标正常但链路无效”的结果文件

## Phase 3. 修 lexical 表达

目标：

- 在正式链路下提升 lexical 的 claim matching 能力

完成标准：

- 标点黏连被修正
- lexical searchable text 完成统一
- 若 dense 再次失效，lexical 结果也不至于明显异常漂移

禁止：

- 为个别 query 加硬编码规则

## Phase 4. 修 fusion / rerank

目标：

- 在 dense 与 lexical 都正常的前提下提升指标

完成标准：

- `candidate_top_k` 与 `metric_top_k` 解耦
- rerank 对有效候选池产生可观测正增益

禁止：

- 在 dense 仍未恢复前继续调 fusion

## Phase 5. 持续复测直到稳定达标

目标：

- 拿到“能复现”的稳定指标，而不是偶然好看的一次结果

完成标准：

- 达到本计划书第 10 节验收线
- 连续复测通过

---

## 9. 文件级执行清单

### [backend/retrieval_core/llamaindex_backend.py](/D:/AI应用/langchain-agent/backend/retrieval_core/llamaindex_backend.py)

- 当前职责：dense build / dense retrieve / lexical build / lexical retrieve / fusion / coalesce
- 动作：
  - 修 dense build-read-verify
  - 修 status truth
  - 接入 searchable text lexical build
  - 解耦 candidate vs final top_k
- done 条件：
  - dense collection 真实可 reopen
  - dense retrieval 非静默空
  - lexical 构建不再只吃裸 `unit.text`

### [backend/retrieval_core/lexical.py](/D:/AI应用/langchain-agent/backend/retrieval_core/lexical.py)

- 当前职责：tokenization、BM25 scoring、text normalization
- 动作：
  - 修 token 边界
  - 固化 biomedical-friendly normalization 最小集合
- done 条件：
  - `PGE2.` / `homocysteine.` 不再带尾部标点入 token

### [backend/tests/scifact_v2_eval.py](/D:/AI应用/langchain-agent/backend/tests/scifact_v2_eval.py)

- 当前职责：正式链路风格 benchmark
- 动作：
  - preflight 检查
  - dense/lexical/fusion observability
  - 输出稳定性复测协议
- done 条件：
  - benchmark 能判断链路是否有效

### [backend/embedding_compat.py](/D:/AI应用/langchain-agent/backend/embedding_compat.py)

- 当前职责：embedding 客户端兼容层
- 动作：
  - 保持轻量，不重新引入重型 llama-index 基类
  - 只补 observability，不改主接口
- done 条件：
  - query embedding 与 index embedding 的维度和 provider 信息可观测

### [backend/document_conversion/docling_converter.py](/D:/AI应用/langchain-agent/backend/document_conversion/docling_converter.py)

- 当前职责：结构化 conversion
- 动作：
  - 本轮仅保留，不做 benchmark 特化
- done 条件：
  - benchmark 仍沿正式链路进入 normalized ingestion

### [backend/normalized_ingestion/chunking.py](/D:/AI应用/langchain-agent/backend/normalized_ingestion/chunking.py)

- 当前职责：unit 生成
- 动作：
  - 仅在需要时增加 metadata observability
- done 条件：
  - 能解释 heading / paragraph / page_summary 对结果的影响

---

## 10. 验证与退出条件

## 10.1 每轮修复后的必跑检查

每次只要有代码变更，必须按顺序执行：

1. dense availability smoke check
2. lexical token smoke check
3. SciFact 50-query 快速评估
4. 对照上轮结果做 diff

若任一步失败：

- 不允许继续宣称“已修好”
- 必须继续进入下一轮修复

## 10.2 阶段性验收线

### 链路健康验收

必须同时满足：

- benchmark dense collection 可 reopen
- dense 查询对指定 sanity query 返回非空
- benchmark 结果明确处于 `hybrid_ready`

### 指标验收

以固定 `50-query SciFact` 快速集为主门槛：

- base retrieval:
  - `accuracy@1 >= 0.54`
  - `hit@10 >= 0.80`
- full chain（rerank 生效后）:
  - `accuracy@1 >= 0.58`
  - `hit@10 >= 0.80`

随后必须追加更大样本验证：

- `max_queries = 300` 或完整测试集
- 指标不允许出现明显回落

## 10.3 稳定性验收

完成指标验收后，必须再做连续复测：

- 相同配置连续运行 3 次
- 指标波动不得超过 `0.01`
- dense availability 不得在任一轮掉回 `0`

若任一项不满足：

- 不允许退出
- 必须继续修复

---

## 10A. 迁移与清理规则

1. 旧 benchmark 特化逻辑保持冻结，不允许回流。
2. dense 修复完成前，不做新的大规模架构迁移。
3. 若最终确认本地 Qdrant path 模式是根因之一，可切换到 Qdrant server 模式，但必须：
   - 先给出验证结论
   - 再单独做切换
   - 保留回滚入口
4. 只有当新链路连续达标后，才允许清理临时诊断代码与临时 artifact。

---

## 11. 执行中的禁止捷径

1. 不用 benchmark 专用切分逻辑刷分。
2. 不把 dense 失效时的 lexical-only 结果当成“系统可用”。
3. 不通过临时硬编码 query 规则修个别失败样本。
4. 不一次性混改 tokenizer、fusion、rerank、切分四类主因。
5. 不在没有连续复测前宣告完成。

---

## 12. 预期结果

当本计划执行完成时，系统应达到以下状态：

1. benchmark 结果首先可信；
2. dense 与 lexical 都是实可用，不是纸面可用；
3. SciFact 快速评估恢复到至少旧基线水平，并在 rerank 后进一步提升；
4. 后续优化可以建立在真实 hybrid 链路上，而不是退化态上。

---

## 13. 持续工作闭环

本次修复不是“一轮改完”的线性任务，而是必须按以下闭环持续推进：

1. 选定当前主坏点  
   只能选一个主因，不允许多主因并行混改。

2. 做最小必要修复  
   只修主因，不顺手扩散。

3. 立即重建或重读相关索引  
   保证验证对象对应最新实现。

4. 立即运行固定测试  
   smoke + SciFact 50-query。

5. 若不达标，输出新的坏点结论  
   不是停下，而是进入下一轮。

6. 只有在“链路健康 + 指标达标 + 连续稳定”全部满足时，才允许退出。

这条闭环是本计划书的硬约束，不是建议。

