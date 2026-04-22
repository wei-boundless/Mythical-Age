# Phase 5 检索重构重新规划计划书

> 编写日期：2026-04-22  
> 对应背景：`docs/42-RAG成熟方案对照与改造执行清单.md`、`docs/43-RAG成熟方案现状审查矩阵-Phase1.md`、`docs/44-结构约束下动态分块实施小清单.md`  
> 目的：在确认上一轮 `Phase 5` 设计越界并已回退后，重新按成熟、可产业化的 RAG 做法规划后续检索重构路线。

---

## 1. 问题重新定义

本轮暴露出来的核心问题，不是“某个融合公式写错了”，而是：

1. 我们把 `前处理契约`、`检索主链迁移`、`benchmark 评测闭环` 混成了一次性重构。
2. 代码状态、索引状态、评测产物一度失配，导致旧结果被误当成当前实现的能力。
3. `docs/44` 的边界被越权外推到了 hybrid 设计，破坏了计划书的执行约束作用。
4. 我们在没有先锁“当前正式基线”的情况下，直接跳到了高风险的 hybrid 主链重写。

因此，这次重构要修的真正系统属性是：

- 阶段边界
- 基线一致性
- 检索链路迁移顺序
- 评测与代码的可追踪一致性

正确的终态不是“立刻上 native hybrid”，而是：

- 先有一个与代码一致、可稳定重建、可稳定评测的正式基线；
- 再在这个基线上逐步迁移 `sparse -> hybrid -> rerank`；
- 每一步都能明确判断：是 ingestion 变了、retriever 变了，还是只是产物状态没对齐。

---

## 2. 当前本地系统现状

基于当前代码审查，系统处于下面这个状态：

### 2.1 已稳定落地的部分

- `document_conversion -> normalized_ingestion -> chunking` 的结构契约已经存在
- 结构约束下的动态分块已落地
- `document_summary / parent_section / leaf_block` 三层节点已生成
- `RetrievalService` 默认仍走 `v2_primary`

### 2.2 当前检索主链的真实状态

当前 [llamaindex_backend.py](/D:/AI应用/langchain-agent/backend/retrieval_core/llamaindex_backend.py) 实际主链是：

`dense retrieval -> application lexical retrieval -> app-side fusion -> coalesce`

也就是说，当前正式代码还不是：

- `Qdrant sparse` 主召回
- `Qdrant native hybrid` 主融合
- `final-grain hybrid` 主链

### 2.3 当前最大的工程风险

最大风险不是“召回不够强”，而是：

- 容易拿旧索引和旧评测结果误判当前代码状态
- 文档 `44` 和后续检索设计之间缺少严格的职责切面
- 一旦直接继续推进 hybrid，极容易再次把 `ingestion` 问题、`retriever` 问题、`artifact` 问题混在一起

---

## 3. 外部成熟方案的产业级共识

本次只抽取与当前问题直接相关、且能落工程的成熟原则。

### 3.1 Microsoft Learn: Advanced RAG

参考：

- <https://learn.microsoft.com/en-us/azure/developer/ai/advanced-retrieval-augmented-generation>

可直接借鉴的原则：

1. 产业级 RAG 必须拆成 `Ingestion / Inference / Evaluation` 三大阶段，而不是边改边混。
2. ingestion 必须先做：
   - 内容预处理
   - chunking 策略
   - chunking 组织
   - update 策略
3. 元数据必须作为正式索引输入保留。
4. chunking 组织应支持：
   - `hierarchical indexes`
   - `Small2Big`
   - summary-first narrowing
5. 更新策略必须显式支持：
   - versioning
   - partial update
   - reindex 策略

### 3.2 Qdrant 官方：Hybrid / Multi-stage / Grouping / Reranking

参考：

- <https://qdrant.tech/documentation/search/>
- <https://qdrant.tech/documentation/search/hybrid-queries/>
- <https://qdrant.tech/documentation/advanced-tutorials/reranking-hybrid-search/>

可直接借鉴的原则：

1. hybrid 不只是 dense+sparse 拼起来，还应支持 filtering、grouping、staged query、reranking。
2. multi-stage query 是正式能力，不是临时 hack。
3. rerank 前应先取较大的 candidate set，再缩到最终 top-k。
4. late interaction / reranking 是第二阶段，不应替代第一阶段召回。
5. 若一个业务对象由多个点组成，应优先考虑分组与业务粒度的一致性，而不是直接把点级排名当最终答案。

### 3.3 AWS 官方：Grounding / Hybrid Retrieval / Rerank / Governance

参考：

- <https://docs.aws.amazon.com/prescriptive-guidance/latest/agentic-ai-serverless/grounding-and-rag.html>
- <https://docs.aws.amazon.com/jp_jp/kendra/latest/dg/searching-retrieve.html>
- <https://docs.aws.amazon.com/bedrock/latest/userguide/rerank-use.html>

可直接借鉴的原则：

1. 企业 RAG 的首要属性是 trust、accuracy、explainability。
2. grounding 之外，还必须有 traceability、access control、update management、observability。
3. passage retrieval 应有明确的长度与数量边界。
4. hybrid search 可以是正式生产能力，但 rerank 必须建立在已有候选集之上。
5. reranker 的职责是重排，不是弥补召回链路设计错误。

---

## 4. 明确借鉴与明确不借鉴

### 4.1 明确借鉴

本仓库后续应明确借鉴下面这些成熟做法：

1. `ingestion / inference / evaluation` 三阶段严格拆分
2. 结构化内容预处理与元数据保留
3. 层级索引或 `Small2Big` 组织
4. hybrid 作为正式检索能力，但必须建立在统一业务粒度与可追踪评测之上
5. rerank 只做第二阶段
6. build/version/eval 的链路版本化

### 4.2 明确不借鉴

这次明确不再采用：

1. 在没有统一基线前，直接切到 native hybrid 主路径
2. 用 benchmark 结果反向定义当前代码结构
3. 在前处理文档里顺带定义 hybrid 主链
4. 让 rerank 承担一阶段主召回补锅职责
5. 用未标记链路版本的旧产物指导新设计

---

## 5. 新的目标设计

## 5.1 设计边界重新锁定

从现在开始，边界固定如下：

### 边界 A. `docs/44`

只负责：

- 结构清洗
- 动态分块
- 三层节点
- 检索输入契约

不负责：

- sparse
- hybrid
- rerank
- 评测主链收益

### 边界 B. 本文档

只负责：

- 检索主链迁移
- build/version/eval 一致性
- sparse/hybrid/rerank 的正式切换顺序
- cutover / rollback

### 边界 C. benchmark

只负责：

- 验证当前正式代码
- 输出有链路版本标记的结果

不允许：

- 继续替代当前代码定义系统状态

## 5.2 目标主链

新的正式目标链路调整为：

`Docling / MinerU -> normalized ingestion -> dynamic chunking -> three-layer nodes -> stable retrieval baseline -> sparse migration -> hybrid candidate comparison -> rerank -> answer assembly`

这里特别强调：

- `stable retrieval baseline` 是一个正式阶段，不再跳过
- `sparse migration` 与 `hybrid candidate comparison` 必须分开
- `rerank` 只能在 hybrid 候选稳定后接入

## 5.3 当前阶段的正式目标

当前最合理的正式目标，不是“立刻做最强 hybrid”，而是：

1. 先把当前 `docs/44` 后版本固化成可重建基线
2. 让 benchmark 只反映当前代码
3. 在基线之上并行比较：
   - app lexical baseline
   - qdrant sparse candidate
   - hybrid candidate
4. 只允许胜出的方案进入下一步 cutover

---

## 6. 固定执行顺序

## Phase 0. 基线冻结与产物清场

目标：

- 让代码、索引、评测三者重新一致

动作：

1. 明确当前正式代码版本
2. 明确当前正式 benchmark root
3. 为所有评测输出补 `chain_version / build_id / index_root / code_commit`
4. 将旧 hybrid 产物标记为历史结果，不再当作当前基线
5. 基于当前代码正式重建一次 benchmark 索引并输出 baseline

完成标准：

- 任意一份评测结果都能反查到代码版本与索引版本

禁止：

- 继续拿旧 `phase5` 结果代表当前代码

## Phase 1. 正式检索基线收口

目标：

- 锁定一个“结构契约正确、检索路径简单、可稳定重建”的 baseline

动作：

1. 固定当前 baseline 为：
   - same ingestion
   - same chunking
   - same three-layer nodes
   - dense + lexical app fusion
2. 检查 `retrieval_modes / score_breakdown / result_granularity` 的真实性
3. 明确 parent/document 上下文在 baseline 中是：
   - 不接
   - 只回填
   - 还是参与排序
   三选一，并写死
4. 完成 baseline 的 50-query 与 300-query 基线报告

完成标准：

- 当前 baseline 结果稳定，重复跑波动可接受

禁止：

- 在 baseline 阶段偷偷接 sparse/hybrid 新逻辑

## Phase 2. Sparse 正式迁移

目标：

- 让 sparse 成为正式候选路径，但还不切主

动作：

1. 用当前 `IndexableUnit` 契约正式生成 sparse 表达
2. 保证 sparse 与 dense 使用同一份节点集
3. 保留 lexical fallback，但显式标记为 degraded
4. 新增 sparse-only 对照评测

完成标准：

- sparse 结果可独立评测、可独立重建、可独立回退

禁止：

- sparse 刚接上就直接接管 hybrid 主链

## Phase 3. Hybrid 候选对照

目标：

- 先比较，再决定，不预设 native hybrid 一定正确

候选方案：

1. `dense + lexical` app fusion baseline
2. `dense + qdrant sparse` app fusion
3. `qdrant native hybrid`

动作：

1. 三种方案共用：
   - 同一 corpus
   - 同一 chunking
   - 同一 unit schema
   - 同一 eval
2. 输出统一对照报告：
   - accuracy@1
   - hit@3
   - hit@5
   - mrr@10
   - latency
   - 失败样本 bucket
3. 仅在对照结果稳定后，才决定是否切主

完成标准：

- 胜出方案明确，且不是一次性偶然跑分

禁止：

- 方案尚未对照完成就切主链

## Phase 4. Rerank 接入

目标：

- 让 rerank 只承担它该承担的职责

动作：

1. 只对有限候选集做 rerank
2. 明确 rerank 前 top-k 与 rerank 后 top-n
3. 输出 `rerank gain / rerank loss` 报告
4. 检查 rerank 是否只是放大错误召回

完成标准：

- rerank 对稳定候选有净收益，且不依赖隐式补锅

禁止：

- 在一阶段检索不稳定时拿 rerank 刷分

## Phase 5. Cutover 与运营化

目标：

- 真正进入产业可运维状态

动作：

1. 固定正式主链
2. 保留显式 rollback
3. 增加 freshness / rebuild / versioning 规则
4. 增加 retrieval trace 与 audit 字段

完成标准：

- 正式主链、降级主链、benchmark 主链三者关系清晰

---

## 7. 文件级执行清单

### 7.1 基线与版本一致性

涉及文件：

- [scifact_v2_eval.py](/D:/AI应用/langchain-agent/backend/tests/scifact_v2_eval.py)
- [service.py](/D:/AI应用/langchain-agent/backend/retrieval/service.py)
- [llamaindex_backend.py](/D:/AI应用/langchain-agent/backend/retrieval_core/llamaindex_backend.py)

动作：

1. 为评测结果补链路版本字段
2. 为索引元数据补 build/version 标识
3. 统一服务层 compare 输出口径

执行顺序：

1. 先改 [scifact_v2_eval.py](/D:/AI应用/langchain-agent/backend/tests/scifact_v2_eval.py)
   产出：
   - `chain_version`
   - `code_commit`
   - `index_root`
   - `build_id`
2. 再改 [llamaindex_backend.py](/D:/AI应用/langchain-agent/backend/retrieval_core/llamaindex_backend.py)
   产出：
   - collection metadata 内的 build/version 字段
   - 重建后可追踪的 index identity
3. 最后改 [service.py](/D:/AI应用/langchain-agent/backend/retrieval/service.py)
   产出：
   - shadow compare 与线上 compare 的统一字段口径

本阶段验收：

- 同一份评测 JSON 能反查 commit
- 同一份索引 metadata 能反查 build
- service compare 输出与评测字段名称不冲突

### 7.2 检索基线收口

涉及文件：

- [llamaindex_backend.py](/D:/AI应用/langchain-agent/backend/retrieval_core/llamaindex_backend.py)
- [retrieval_core_phase2_regression.py](/D:/AI应用/langchain-agent/backend/tests/retrieval_core_phase2_regression.py)
- [retrieval_service_cutover_regression.py](/D:/AI应用/langchain-agent/backend/tests/retrieval_service_cutover_regression.py)

动作：

1. 锁定 baseline 检索行为
2. 锁定 `retrieval_modes / breakdown / granularity`
3. 停止漂移式修改

执行顺序：

1. 先改 [llamaindex_backend.py](/D:/AI应用/langchain-agent/backend/retrieval_core/llamaindex_backend.py)
   只做：
   - baseline 主链固定
   - `retrieval_modes` 定义固定
   - `score_breakdown` 字段固定
   - `result_granularity` 字段固定
2. 再改 [retrieval_core_phase2_regression.py](/D:/AI应用/langchain-agent/backend/tests/retrieval_core_phase2_regression.py)
   只验证：
   - baseline 行为
   - 模式字段
   - 粒度字段
3. 最后改 [retrieval_service_cutover_regression.py](/D:/AI应用/langchain-agent/backend/tests/retrieval_service_cutover_regression.py)
   只验证：
   - service 输出字段
   - shadow compare 统计

本阶段验收：

- baseline 查询重复执行行为不漂移
- `retrieval_modes` 不再一会儿叫 `lexical` 一会儿叫 `sparse`
- 粒度字段定义对所有 query mode 一致

### 7.3 Sparse 迁移

涉及文件：

- [lexical.py](/D:/AI应用/langchain-agent/backend/retrieval_core/lexical.py)
- [llamaindex_backend.py](/D:/AI应用/langchain-agent/backend/retrieval_core/llamaindex_backend.py)

动作：

1. 把 sparse 供料层与 fallback 检索层分离
2. 给 sparse-only 建独立评测口径

执行顺序：

1. 先改 [lexical.py](/D:/AI应用/langchain-agent/backend/retrieval_core/lexical.py)
   拆成两类职责：
   - sparse payload 供料
   - lexical fallback 检索
2. 再改 [llamaindex_backend.py](/D:/AI应用/langchain-agent/backend/retrieval_core/llamaindex_backend.py)
   接入：
   - sparse-only 路径
   - degraded fallback 标记
3. 最后改 [scifact_v2_eval.py](/D:/AI应用/langchain-agent/backend/tests/scifact_v2_eval.py)
   输出：
   - baseline
   - sparse-only
   - degraded fallback

本阶段验收：

- sparse-only 可以独立重建和独立评测
- fallback 触发时有显式标记
- 不再用 lexical fallback 冒充正式 sparse

### 7.4 Hybrid 候选比较

涉及文件：

- [llamaindex_backend.py](/D:/AI应用/langchain-agent/backend/retrieval_core/llamaindex_backend.py)
- [scifact_v2_eval.py](/D:/AI应用/langchain-agent/backend/tests/scifact_v2_eval.py)

动作：

1. 并行保留多种候选方案
2. 统一输出对照结果
3. 不在此阶段直接清旧主链

执行顺序：

1. 先改 [llamaindex_backend.py](/D:/AI应用/langchain-agent/backend/retrieval_core/llamaindex_backend.py)
   增加显式策略开关：
   - `baseline_dense_lexical`
   - `dense_sparse_app_fusion`
   - `qdrant_native_hybrid`
2. 再改 [scifact_v2_eval.py](/D:/AI应用/langchain-agent/backend/tests/scifact_v2_eval.py)
   让同一批 query 共跑多种策略
3. 最后输出对照报告
   统一字段：
   - metrics
   - latency
   - failure buckets
   - chain version

本阶段验收：

- 三种策略共用同一份索引与 query 集
- 对照报告能直观看出谁赢、赢在哪里、代价是什么
- 在此之前不得切任何新主链

### 7.5 Rerank 接入

涉及文件：

- [service.py](/D:/AI应用/langchain-agent/backend/retrieval/service.py)
- [scifact_v2_eval.py](/D:/AI应用/langchain-agent/backend/tests/scifact_v2_eval.py)
- [retrieval_service_cutover_regression.py](/D:/AI应用/langchain-agent/backend/tests/retrieval_service_cutover_regression.py)

动作：

1. 固定 rerank 输入候选数
2. 固定 rerank 输出截断数
3. 输出 rerank 净收益与净损失报告

执行顺序：

1. 先在 [service.py](/D:/AI应用/langchain-agent/backend/retrieval/service.py) 锁候选规模
2. 再在 [scifact_v2_eval.py](/D:/AI应用/langchain-agent/backend/tests/scifact_v2_eval.py) 补 rerank 对照
3. 最后在 [retrieval_service_cutover_regression.py](/D:/AI应用/langchain-agent/backend/tests/retrieval_service_cutover_regression.py) 固化服务行为

本阶段验收：

- rerank 不再隐式改变召回候选规模
- rerank 收益和损失都可解释
- rerank 关闭时 baseline 行为不变

### 7.6 Cutover 与运维化

涉及文件：

- [service.py](/D:/AI应用/langchain-agent/backend/retrieval/service.py)
- [config.py](/D:/AI应用/langchain-agent/backend/config.py)
- [scifact_v2_eval.py](/D:/AI应用/langchain-agent/backend/tests/scifact_v2_eval.py)

动作：

1. 明确正式策略名
2. 明确 rollback 策略名
3. 明确 benchmark 使用哪条正式链路

执行顺序：

1. 先在 [config.py](/D:/AI应用/langchain-agent/backend/config.py) 固化策略枚举
2. 再在 [service.py](/D:/AI应用/langchain-agent/backend/retrieval/service.py) 固化 cutover 分支
3. 最后在 [scifact_v2_eval.py](/D:/AI应用/langchain-agent/backend/tests/scifact_v2_eval.py) 保证 benchmark 与正式策略映射清晰

本阶段验收：

- `legacy_only / shadow_read / v2_primary` 之外的策略语义清楚
- benchmark 不再绕开正式策略入口
- rollback 可在不改代码的情况下切回

---

## 8. 验证矩阵

### 8.1 基线一致性

- 代码、索引、评测产物是否同版本
- benchmark 是否只反映当前代码

### 8.2 结构契约

- `docs/44` 的分块与三层节点是否稳定
- retrieval 是否没有重新发明切分逻辑

### 8.3 检索对照

- baseline
- sparse-only
- hybrid candidate
- rerank-on-top

### 8.4 稳定性

- 同一版本连续跑 3 次
- 指标波动和 latency 波动均需记录

---

## 9. Cutover 与 Rollback

## 9.1 Cutover 原则

只有同时满足下面条件，才允许切主链：

1. 当前 baseline 已可稳定重建
2. 新候选方案指标稳定优于 baseline
3. 评测产物与代码版本完全一致
4. 回归测试全部通过

## 9.2 Rollback 原则

出现以下任一情况，立即回退到 baseline：

1. 代码状态与产物状态失配
2. accuracy@1 提升不稳定
3. rerank 仅靠补锅维持收益
4. retrieval metadata 失真，无法诊断

---

## 10. 完成判定

只有同时满足下面条件，才允许认为这轮检索重构真正完成：

- [ ] `docs/44` 的边界已不再被检索方案越权修改
- [ ] 当前正式 baseline 已完成锁定与重建
- [ ] sparse 已成为正式候选能力
- [ ] hybrid 已通过与 baseline 的正式对照
- [ ] rerank 已建立在稳定候选之上
- [ ] benchmark / code / index 三者版本一致
- [ ] rollback 路径仍然存在

如果任一项未满足，就说明这轮检索重构仍未完成，不能宣布正式收口。
