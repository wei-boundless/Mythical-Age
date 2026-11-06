---
title: General 子 agent 结果整合工作提示
---

把子 agent 返回当作证据输入，不是最终答案。
先检查 scope、positive findings、negative findings、sources/files read、evidence_refs、limitations、open_questions 和 recommended_parent_action。
多个结果冲突时，按证据来源、时间、新鲜度、读取范围和直接性裁决；无法裁决时说明限制或继续验证。
如果子 agent 的行动建议互相冲突，优先采用用户最新目标和当前任务合同支持、证据直接、可验证且副作用最小的建议；仍冲突时由你读取关键证据后裁决，不能把冲突外包给用户。
