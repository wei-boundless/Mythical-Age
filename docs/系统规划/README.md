# 洪荒时代系统规划

本目录用于沉淀洪荒时代（mythical ageent）的新架构规划。

这里的文档优先回答：

- 子系统的职责边界是什么。
- 哪些旧连线已经清空。
- 新契约如何定义。
- 后续代码应该按什么顺序落地。

当前规划主线：

1. 灵魂系统完整构建。
2. 任务系统与灵魂意志联动。
3. 灵魂管理、prompt 收束与多态投影。
4. AgentProfile 与协作模式系统。
5. Skill / Tool / Worker 子单元规范化。
6. ControlKernel / ExecutionGraph / RuntimeDirective 重新接线。
7. Memory / CommitGate / 测试报告系统重构。

当前文档：

- `00-洪荒时代AgentRuntime总框架-20260429.md`
- `操作系统与任务系统/00-设计原则继承与重构约束.md`
- `操作系统与任务系统/01-任务系统重构实施计划-20260429.md`
- `操作系统与任务系统/02-操作系统重构实施计划-20260429.md`
- `操作系统与任务系统/03-任务系统与操作系统接线方案-20260429.md`
- `操作系统与任务系统/04-编排系统重构设计准备-20260429.md`
- `操作系统与任务系统/05-编排系统架构设计-20260429.md`
- `操作系统与任务系统/06-编排系统阶段收口-20260429.md`
- `操作系统与任务系统/07-query目录拆分与旧链路清理方案-20260430.md`
- `记忆系统/00-记忆系统重构设计准备-20260429.md`
- `记忆系统/01-记忆系统与上下文管理架构设计-20260429.md`

当前定稿方向：

```text
洪荒时代不是一个更大的 query runtime，而是一套分层 agent runtime。
灵魂系统不是语气包，而是智能体意志管理层。
灵魂可以理解 tools / skills，但授权仍然由 ControlKernel / ResourcePolicy 决定。
所有进入模型的 prompt section 后续都应通过 SoulProjection / PromptManifest 收束。
旧 query 层应逐步退化为请求入口、事件流和过渡 adapter。
```

当前施工状态：

```text
灵魂系统：已完成主要重构。
任务系统：preview contract 已接入。
操作系统：ResourcePolicyPreview 已接入。
编排系统：single_agent preview 控制面已收口，真实执行面暂停。
记忆系统：已完成重构准备与上下文管理架构设计，下一步进入合同层施工。
query 旧层：已完成目录级追踪，下一步先收缩 QueryRuntime 初始化面，再迁出 output / prompt / evidence 等保留能力。
```
