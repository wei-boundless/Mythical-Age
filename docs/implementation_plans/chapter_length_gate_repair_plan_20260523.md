# 章节字数质量门修复计划

## 问题判断

当前写作图已经把 `chapter_draft` 注册为每批目标 20000 字、最低 18000 字、每章最低 1800 字，但运行时验收优先执行 `length_budget` 后直接返回，导致 `sectioned_text_batch_quality` 的逐章统计和短板诊断没有进入返修上下文。写手收到的返修压力主要是总字数不足，缺少“第几章少多少字”的硬信息，容易反复短写。

## 修复原则

1. 字数约束必须作为运行时质量门，而不是只依赖 prompt。
2. 总量约束和逐章约束要合并诊断，不允许互相遮蔽。
3. 返修输入必须携带机器可读和人类可读的短板摘要。
4. 该修复应保持通用质量门能力，不写死《洪荒时代》或小说任务特例。

## 实施步骤

1. 改造 `stage_business_acceptance`：当存在 `length_budget` 且 `quality_retry_policy.acceptance_policies` 包含 `sectioned_text_batch_quality` 时，同时运行两个质量门并合并结果。
2. 增加合并诊断字段：保留总量统计、逐章统计、逐章缺口、合并 issues 和清晰的 quality issue summary。
3. 改造质量返修输入渲染：在 `{quality_issues}` 之外补充可模板引用的 `quality_issue_summary`。
4. 补回归测试：覆盖总量门不再遮蔽逐章门，以及返修需求能携带逐章短板摘要。
5. 运行相关测试并重新注册写作图配置。
