# Phase 5 Hybrid 最终粒度融合修复执行计划书

> 编写日期：2026-04-22  
> 对应背景：`docs/42-RAG成熟方案对照与改造执行清单.md` 中 `Phase 5`  
> 目标：针对当前 `Qdrant native RRF + lexical fallback` 链路中“`hybrid` 的整体排序质量有所提升，但 `accuracy@1` 仍低于 `lexical-only`”的问题，完成一次面向正式主链的结构修复计划，明确坏点、目标设计、实施顺序、回滚边界和验收规则，直到 `hybrid top1` 在正式测试集上稳定优于 `lexical fallback`。

---

## 1. 问题定义

当前问题不是“RRF 参数还没调好”，而是：

- `hybrid` 已经接通，但融合发生的位置和粒度仍不符合成熟 RAG 主链原则；
- 系统在叶子级候选上先做 native RRF，再在应用层收口到 `doc/page/object` 粒度；
- 这会让 lexical 在 top1 上原本很强的精确命中被提前压平；
- 因而出现“`hit@3 / hit@5 / mrr@10` 上升，但 `accuracy@1` 反而下降”的结构性症状。

换句话说，当前坏掉的不是“有没有 hybrid”，而是：

`最终返回粒度的所有权` 仍不在融合之前，而在融合之后。

这与本仓库既有目标设计直接冲突：

- 成熟方案要求：`dense 与 sparse 必须在同一最终返回粒度上融合`
- 当前实现实际是：`leaf-level native fusion -> app-side coalesce to final grain`

因此本计划书要修复的是一个明确的系统设计问题：

**把 hybrid 的融合单位从“叶子命中点”改成“最终返回粒度对象”，并把该规则固化成正式主链，而不是继续靠参数微调补救。**

---

## 2. 当前坏点与证据

## 2.1 正式验收结果

本轮正式构建和验收产物：

- [scifact_phase5_build_report.json](/D:/AI应用/langchain-agent/output/scifact_phase5_build_report.json)
- [scifact_phase5_hybrid_vs_lexical.json](/D:/AI应用/langchain-agent/output/scifact_phase5_hybrid_vs_lexical.json)
- [scifact_phase5_detailed_diff.json](/D:/AI应用/langchain-agent/output/scifact_phase5_detailed_diff.json)

当前 300-query SciFact test 结果：

- `hybrid`
  - `accuracy@1 = 0.5167`
  - `hit@3 = 0.7100`
  - `hit@5 = 0.7967`
  - `mrr@10 = 0.6292`
- `lexical_fallback`
  - `accuracy@1 = 0.5267`
  - `hit@3 = 0.6667`
  - `hit@5 = 0.7167`
  - `mrr@10 = 0.6129`

这说明：

1. `hybrid` 不是完全失败。
2. `hybrid` 的中后位排序质量优于 `lexical fallback`。
3. 但 `top1` 仍然输给 `lexical fallback`。

因此当前首要坏点不是“召回彻底坏掉”，而是“融合顺序和粒度让正确答案在 top1 被压下去”。

## 2.2 逐题差异证据

在 [scifact_phase5_detailed_diff.json](/D:/AI应用/langchain-agent/output/scifact_phase5_detailed_diff.json) 中，300 条 query 的差异分布为：

- `both_correct = 135`
- `both_wrong = 122`
- `hybrid_only = 20`
- `lexical_only = 23`

这意味着：

- `hybrid` 只比 `lexical fallback` 净少赢了 3 条 top1；
- 不是大面积掉分，而是少量 top1 排名被压错。

更关键的是，在已抽样保存的 `lexical_only` 样本中：

- 大多数 query 中，`hybrid` 仍然把 gold 文档放进了 `top3` 或 `top5`
- 只有极少数 query 是 gold 被完全挤出 `top5`

这进一步说明：

- 主问题是 `top1 ranking` 被压平；
- 次问题才是个别 query 的 dense 假阳性或 sparse 噪声过强。

## 2.3 当前代码坏点

### 坏点 A. native hybrid 发生在最终返回粒度之前

当前主路径：

- [llamaindex_backend.py](/D:/AI应用/langchain-agent/backend/retrieval_core/llamaindex_backend.py)

关键位置：

- `retrieve()` 优先走 native hybrid
- `_retrieve_hybrid_qdrant()` 直接对 Qdrant 叶子点执行 `FusionQuery(RRF)`
- `_finalize_collection_hits()` 在 native hybrid 之后才做 `result_granularity` 收口

这意味着当前结构是：

`leaf query -> native RRF -> app-side coalesce -> final grain`

而不是目标结构：

`dense leaf recall -> sparse leaf recall -> final grain aggregation -> final grain fusion`

### 坏点 B. `dense/sparse` 的返回粒度在 native hybrid 路径中不可见

当前已经在：

- `_result_granularity()`
- `_coalesce_key()`

中定义了 `document / page / object` 三类最终返回粒度。

但这些规则只在应用层的后处理里发挥作用，并没有前移到 native hybrid 之前。

直接后果：

- `RRF` 看到的是叶子命中，不是最终返回对象；
- 同一个 doc 下多个弱相关 leaf 可能会共同抬高一个错误 top1；
- lexical 本来精确命中的 doc 反而因为只贡献单点排名，在 leaf-level fusion 中被压下去。

### 坏点 C. native hybrid 的 `retrieval_modes` 标注过粗

当前 `_retrieve_hybrid_qdrant()` 对所有返回统一打：

- `("dense", "sparse", "hybrid_native")`

但从现有样本可见，部分命中只有 `dense` breakdown，没有 `sparse` breakdown。

直接后果：

- service 统计中的 `sparse_hit_count / hybrid_native_hit_count` 会被污染；
- 后续想根据 breakdown 决定是否做 lexical boost 或 dense gate 时，依据不可信。

### 坏点 D. native hybrid 仍缺少“top1 保护”原则

当前 `semantic_lookup` 下直接使用统一的 RRF。

但从 SciFact 结果看：

- lexical 对某些 claim 类 query 的 top1 非常强；
- native RRF 在这些 query 上会把正确 top1 压成 top2/top3；
- 系统没有任何“exact sparse winner”保护或“高置信 lexical top1 守门”机制。

这里的关键不是回退到 lexical-only，而是：

在最终粒度融合后，允许对明显的高置信 sparse exact match 做受控保护。

---

## 3. 本地设计约束

本计划书必须服从以下既有文档和原则：

- [41-RAG检索持续修复与稳定达标计划书.md](/D:/AI应用/langchain-agent/docs/41-RAG检索持续修复与稳定达标计划书.md)
- [42-RAG成熟方案对照与改造执行清单.md](/D:/AI应用/langchain-agent/docs/42-RAG成熟方案对照与改造执行清单.md)
- [43-RAG成熟方案现状审查矩阵-Phase1.md](/D:/AI应用/langchain-agent/docs/43-RAG成熟方案现状审查矩阵-Phase1.md)
- [44-结构约束下动态分块实施小清单.md](/D:/AI应用/langchain-agent/docs/44-结构约束下动态分块实施小清单.md)

提炼出的强约束如下：

1. 不允许 benchmark 特化捷径进入主链。
2. 不允许为了个别 query 刷分而硬编码规则。
3. 结构修复优先于 prompt 或参数修复。
4. 最终返回粒度必须是正式规则，而不是事后拼接。
5. 任何迁移都要保留 cutover 和 rollback。
6. 必须先锁执行顺序，再写代码。

---

## 4. 外部成熟方案可借鉴点

本次只借鉴“与当前问题直接相关”的成熟做法，不做泛泛框架综述。

## 4.1 Qdrant Hybrid Search

参考：

- <https://qdrant.tech/documentation/search/hybrid-queries/>

可借鉴点：

- Qdrant 原生 `prefetch + fusion` 适合作为底座；
- 但前提是调用方已经知道“要融合的对象是什么”；
- 如果业务最终关心的是 doc/page/object，而不是 leaf point，那么调用方就必须先把候选映射到业务粒度。

## 4.2 LlamaIndex Fusion / Auto Merging 思路

参考：

- <https://developers.llamaindex.ai/python/framework-api-reference/retrievers/auto_merging/>
- <https://developers.llamaindex.ai/python/framework-api-reference/retrievers/recursive/>

可借鉴点：

- 叶子召回与父级归并是两个阶段；
- 不能把叶子级排序直接当成最终业务排序；
- 最终展示对象和初始召回对象应该分层处理。

## 4.3 BEIR / SciFact 评测启示

参考：

- <https://arxiv.org/abs/2104.08663>

可借鉴点：

- 对 claim retrieval，`top1` 往往比平滑的 rank 指标更敏感；
- 因此如果 `mrr@10` 提升而 `accuracy@1` 下降，优先怀疑的是 top1 ranking logic，不是简单地“hybrid 更好了”。

---

## 5. 设计取舍

## 5.1 不采用的方案

### 方案 A. 继续只调 RRF 参数或 prefetch 深度

问题：

- 只能缓解，不解决“融合单位错了”的根因；
- 可能把一部分 query 修好，但长期不可维护。

结论：

- 不采用为主方案；
- 只允许在结构修复完成后做小范围微调。

### 方案 B. 回退到 lexical top1 主导

问题：

- 这等于承认 native hybrid 主链失败；
- 会把 `Phase 5` 变成“用 fallback 冒充正式结果”。

结论：

- 不采用为主方案；
- lexical 只保留为 fallback 与诊断对照。

### 方案 C. 直接上跨编码器 rerank 补 top1

问题：

- rerank 只应做第二阶段；
- 当前 top1 问题发生在一阶段融合，不应让 rerank 背锅。

结论：

- 本轮不采用。

## 5.2 采用的方案

采用的正式方向是：

**把 hybrid 改成“两阶段融合”**

1. `dense/sparse` 仍在 leaf 层召回；
2. 先分别收口到最终业务粒度 `doc/page/object`；
3. 再在这个最终粒度上做融合；
4. 最后再根据 query_mode 应用有限的 top1 保护或 tie-break 规则。

这是本轮唯一推荐方向。

---

## 6. 目标设计

## 6.1 canonical truth

关于 “最终结果对象是谁” 的 canonical truth 固定如下：

- `semantic_lookup`：默认 `document`，若命中 `object_ref_id` 则允许 `object`
- `page_grounded_lookup`：优先 `page`，若是显式对象则 `object`
- `table_lookup`：优先 `object`，其次 `page`，最后 `document`
- `document_overview`：只允许 `document`

这个规则已经有雏形，但必须前移为 hybrid 前的正式聚合规则，而不是只在结果元数据里声明。

## 6.2 各阶段职责

### Stage A. leaf recall

输入：

- query
- dense leaf index
- sparse leaf index

输出：

- dense leaf candidates
- sparse leaf candidates

允许：

- dense/sparse 各自独立 top_k

禁止：

- 在这一阶段直接决定最终 top1

### Stage B. final-grain aggregation

输入：

- dense leaf candidates
- sparse leaf candidates
- `query_mode -> result_granularity` 规则

输出：

- dense final-grain candidates
- sparse final-grain candidates

允许：

- 同一 doc/page/object 下多 leaf 合并
- 保留来源 leaf ids、max score、evidence snippets

禁止：

- 不同最终对象之间提前融合

### Stage C. final-grain fusion

输入：

- dense final-grain candidates
- sparse final-grain candidates

输出：

- fused final-grain ranking

允许：

- RRF 或可解释加权策略
- query-mode 特定 tie-break

禁止：

- 回到 leaf 级别重排

### Stage D. present / context expansion

输入：

- fused final-grain ranking

输出：

- 带 `parent_context / document_context / score_breakdown / result_granularity` 的正式结果

禁止：

- 在这一阶段改变排序主结论

## 6.3 top1 保护原则

只允许在最终粒度阶段做轻量保护，不允许 query 硬编码。

允许的弱规则：

- 若 sparse final-grain top1 与 dense final-grain top1 不同，但 sparse top1 具有明显 exact-entity / exact-claim 优势，可作为 tie-break 信号
- 该信号只能在：
  - 分数非常接近
  - sparse 命中文本覆盖率显著更高
  - dense 并无明显语义领先
  时生效

不允许：

- 直接“lexical 胜就 lexical 第一”
- 单 query 规则表

---

## 7. 固定执行流

本次修复必须严格按下面顺序推进。

## Phase A. 审计与冻结

目标：

- 固化当前失败样本和基线结果

输入：

- [scifact_phase5_hybrid_vs_lexical.json](/D:/AI应用/langchain-agent/output/scifact_phase5_hybrid_vs_lexical.json)
- [scifact_phase5_detailed_diff.json](/D:/AI应用/langchain-agent/output/scifact_phase5_detailed_diff.json)

输出：

- top1 掉分样本集
- 结构性坏点结论

禁止：

- 先改参数再归因

## Phase B. 分离 leaf recall 与 final-grain aggregation

目标：

- 让 dense/sparse 先各自聚合到最终粒度

输出：

- `dense_final_candidates`
- `sparse_final_candidates`

完成标准：

- `semantic_lookup` 下，doc 级融合前不再直接使用 leaf rank
- `page_grounded_lookup` / `table_lookup` 的 page/object 规则有独立测试

禁止：

- 仍在 leaf-level native fusion 后再 coalesce

## Phase C. 改造 final-grain fusion

目标：

- 在最终粒度对象上重新定义 fusion

输出：

- `fused_final_candidates`
- 完整 breakdown：`dense / sparse / fusion / final`

完成标准：

- 能明确解释某个 top1 是如何赢出来的

禁止：

- breakdown 继续伪装为“所有命中都来自 dense+sparse”

## Phase D. 受控 top1 保护

目标：

- 只修少量“lexical 本来 top1 对，但 RRF 压平”的 query

输出：

- 通用 tie-break 规则

完成标准：

- `accuracy@1` 不再低于 `lexical fallback`

禁止：

- query 白名单
- 词表硬编码刷分

## Phase E. 验收与收口

目标：

- 证明 Phase 5 真正通过

完成标准：

- `hybrid accuracy@1 > lexical-only`
- 连续复测稳定
- rollback 路径仍可用

---

## 8. 文件级实施清单

## 8.1 [llamaindex_backend.py](/D:/AI应用/langchain-agent/backend/retrieval_core/llamaindex_backend.py)

当前问题：

- `native hybrid` 发生在 leaf-level
- `retrieval_modes` 过粗
- `result_granularity` 仅在融合后声明，不在融合前生效

动作：

1. 拆出 `dense leaf recall` 与 `sparse leaf recall`
2. 新增 `final-grain aggregation` 层
3. 让 `_coalesce_key()` 只服务于 final-grain aggregation，不再兼作事后补救
4. 在 final-grain candidate 上重新定义 fusion
5. 修正 `retrieval_modes` 为真实来源集合，而不是统一写死
6. 明确 `score_breakdown` 的字段协议

完成标准：

- `dense/sparse 先聚合，再融合`
- `score_breakdown` 可解释
- `top1` 掉分样本可被系统性缩减

## 8.2 [lexical.py](/D:/AI应用/langchain-agent/backend/retrieval_core/lexical.py)

当前问题：

- 仍承担 fallback 与供料双职责

动作：

1. 保持 tokenization / sparse payload 供料能力
2. 不在本轮继续扩展评分职责
3. 为 top1 保护提供“exact match / query coverage”类弱信号时，只暴露通用特征，不直接排序

完成标准：

- lexical 不再决定主融合，只提供 sparse 特征和 fallback

## 8.3 [service.py](/D:/AI应用/langchain-agent/backend/retrieval/service.py)

当前问题：

- 已有 `hybrid_native_hit_count`，但还缺少 final-grain 级观测

动作：

1. 增加 `result_granularity` 统计
2. 增加 `dense_only / sparse_only / hybrid_shared` 统计
3. shadow compare 里明确区分 native hybrid 与 fallback hybrid

完成标准：

- 服务层能直接看出一次查询到底走了什么融合路径

## 8.4 [scifact_v2_eval.py](/D:/AI应用/langchain-agent/backend/tests/scifact_v2_eval.py)

当前问题：

- 还没有直接输出 `hybrid top1` 为何输给 lexical

动作：

1. 增加逐题 diff 输出
2. 增加 `top1 loss bucket` 汇总
3. 增加 `hybrid vs lexical` 最终粒度对照

完成标准：

- 每次回归后都能快速看到 top1 损失来自哪里

---

## 9. 验证矩阵

## 9.1 功能回归

必须覆盖：

- `semantic_lookup` 返回 `document/object`
- `page_grounded_lookup` 返回 `page/object`
- `table_lookup` 返回 `object/page/document`
- `document_overview` 只返回 `document`

## 9.2 breakdown 回归

必须覆盖：

- `dense-only` 命中不应带伪 `sparse`
- `sparse-only` 命中不应带伪 `dense`
- native hybrid 命中应保留真实 breakdown

## 9.3 指标回归

快速集：

- 50-query SciFact

正式集：

- 300-query SciFact test

硬门槛：

- `hybrid accuracy@1 >= lexical accuracy@1`
- `hybrid mrr@10 > lexical mrr@10`
- 最好同时保持 `hit@3 / hit@5` 不回退

## 9.4 稳定性回归

要求：

- 相同索引、相同配置下连续跑 3 次
- `accuracy@1` 波动不得超过 `0.01`

---

## 10. cutover 与 rollback 规则

## 10.1 cutover

只有同时满足下面条件，才允许认为新 `Phase 5` 主链可以切为正式状态：

- final-grain fusion 已替换 leaf-level native fusion 作为主路径
- SciFact 300-query 上 `hybrid top1` 不再低于 `lexical fallback`
- 相关回归全部通过

## 10.2 rollback

若出现以下任一情况，必须立即回滚到当前可运行状态：

- final-grain aggregation 让 `hit@5` 大幅下降
- native hybrid 结果为空的比例异常升高
- service 统计口径失真，无法继续诊断

回滚方式：

- 保留当前 `qdrant_native_rrf_with_lexical_fallback` 路径
- 新实现以 feature flag 或明确分支方式接入，不直接覆盖旧逻辑

---

## 11. 执行中的禁区

1. 不允许直接把 lexical top1 当正式答案。
2. 不允许只调 `prefetch_limit` 当作主修复方案。
3. 不允许把 rerank 提前拿来补一阶段融合缺陷。
4. 不允许 benchmark 特化 query 规则。
5. 不允许 query 白名单或 claim 模板硬编码。

---

## 12. 完成判定

只有同时满足下面条件，才允许认为这次 `Phase 5` 修复完成：

- [ ] `dense/sparse` 已先在最终返回粒度上聚合，再融合
- [ ] native hybrid 的 `retrieval_modes` 与 `score_breakdown` 已真实可解释
- [ ] 300-query SciFact 上 `hybrid accuracy@1` 已稳定高于 `lexical fallback`
- [ ] `mrr@10 / hit@3 / hit@5` 不发生明显回退
- [ ] 相关 regression 全部通过
- [ ] rollback 路径仍然存在

只要其中任一项不满足，就说明 `Phase 5` 仍未完成，不能宣布“正式收口”。
