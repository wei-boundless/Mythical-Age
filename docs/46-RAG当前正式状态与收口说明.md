# RAG当前正式状态与收口说明

> 编写日期：2026-04-23  
> 目的：对当前正式 RAG 主链、默认配置、评测结论与剩余收尾项做一次性收口说明，避免后续再通过旧计划书反推当前代码状态。

---

## 1. 当前正式状态

截至本次收口，项目中的正式 RAG 主链已经固定为：

`dense retrieval -> application lexical retrieval -> application fusion -> coalesce -> optional rerank`

对应实现入口：

- [llamaindex_backend.py](/D:/AI应用/langchain-agent/backend/retrieval_core/llamaindex_backend.py)
- [service.py](/D:/AI应用/langchain-agent/backend/retrieval/service.py)
- [router.py](/D:/AI应用/langchain-agent/backend/RAG/router.py)
- [reranker.py](/D:/AI应用/langchain-agent/backend/RAG/reranker.py)

当前默认后端状态：

- 向量库默认使用 `Qdrant`
- dense 检索默认走 `llamaindex_v2`
- lexical 检索仍为应用侧 `BM25`
- rerank 默认启用本地 `BAAI/bge-reranker-v2-m3`

---

## 2. 当前默认配置

当前正式默认 rerank 配置位于：

- [backend/.env](/D:/AI应用/langchain-agent/backend/.env)

关键项如下：

- `RERANK_ENABLED=True`
- `RERANK_PROVIDER=cross_encoder`
- `RERANK_MODEL=D:\model\bge-reranker-v2-m3`
- `RERANK_DEVICE=cuda`
- `RERANK_BATCH_SIZE=4`
- `RERANK_MAX_LENGTH=512`

这表示当前正式系统已经不再依赖远端 rerank API，也不再依赖 HuggingFace 缓存路径。

---

## 3. 评测结论

### 3.1 本地知识库

本地知识库对照评测产物：

- [local_knowledge_eval_bge_20260423.json](/D:/AI应用/langchain-agent/output/local_knowledge_eval_bge_20260423.json)

本轮结论：

- baseline `hit@1 = 0.80`
- rerank `hit@1 = 0.85`
- baseline `hit@3 = 0.85`
- rerank `hit@3 = 0.90`
- baseline `mrr@5 = 0.8375`
- rerank `mrr@5 = 0.8667`

结论：在当前本地知识库上，`bge-reranker-v2-m3` 相比 baseline 是正收益，可以保留为默认 rerank。

### 3.2 SciFact 基准

SciFact 对照产物：

- [scifact_v2_bge_50_20260423_base.json](/D:/AI应用/langchain-agent/output/scifact_v2_bge_50_20260423_base.json)
- [scifact_v2_bge_50_20260423_rerank.json](/D:/AI应用/langchain-agent/output/scifact_v2_bge_50_20260423_rerank.json)

本轮结论：

- `accuracy@1` 持平
- `hit@3` 持平
- `hit@5` 略降
- `ndcg@10` 略升

结论：在标准 benchmark 上，当前 rerank 不是显著增益，但也不是灾难性回退；在本地业务知识库上更有价值。

---

## 4. 已收口事项

本次确认已经完成的收口动作：

1. 正式主链统一到当前代码，不再沿用旧 phase5 实验链路。
2. 默认向量库固定为 `Qdrant`。
3. 默认 rerank 固定为本地 `BAAI/bge-reranker-v2-m3`。
4. 失效模型已清理：
   - 本地 `ms-marco-MiniLM-L-2-v2`
   - `Ollama` 中的 `Qwen3-Reranker-0.6B`
5. 本地 rerank 模型已迁移到固定目录：
   - `D:\model\bge-reranker-v2-m3`
6. 新增本地知识库对照评测脚本：
   - [local_knowledge_eval.py](/D:/AI应用/langchain-agent/backend/tests/local_knowledge_eval.py)
7. 回归门禁已补充当前 retrieval / rerank 相关测试：
   - `cross_encoder_rerank_regression`
   - `remote_rerank_regression`
   - `retrieval_core_phase2_regression`
   - `retrieval_service_cutover_regression`

---

## 5. 仍然存在的剩余问题

当前还不能宣称“所有计划项全部完成”，剩余问题主要在以下几类：

1. 表格类查询仍有弱点，例如库存、员工、客户分布等问题，baseline 与 rerank 都不是全稳。
2. 短安全文档类查询仍可能被 AI 报告类内容干扰，例如 `CORS` 一类短问答。
3. 工作树仍处于未提交状态，说明当前是“正式可运行”而不是“历史已归档”。
4. `docs/44` 对应的动态分块边界已经明确，但不应与 rerank 收益混为一个完成条件。

---

## 6. 当前建议

当前最合理的使用方式是：

- 把这套链路视为“正式默认可运行版本”
- 后续优化优先放在：
  - 表格类查询召回
  - 短文档 lexical 命中
  - 本地知识库回归集扩充

不建议当前再做：

- 回到远端 rerank 作为默认方案
- 恢复 MiniLM 轻量 rerank
- 重新引入旧的 phase5 粒度实验链路

---

## 7. 判断结论

更准确的状态判断应该是：

- `RAG 正式主链重构：已完成`
- `RAG 项目整体历史归档与长期优化：未完成`

也就是说，系统已经可以按当前正式设计稳定运行；后续工作应转为“持续优化”和“版本归档”，而不是继续把主链当作未定状态处理。
