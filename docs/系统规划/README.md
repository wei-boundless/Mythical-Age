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

- `01-灵魂系统完整构建方案-20260427.md`
- `02-任务系统与灵魂意志联动方案-20260427.md`
- `03-灵魂系统管理与多态投影方案-20260427.md`

当前定稿方向：

```text
灵魂系统不是语气包，而是智能体意志管理层。
灵魂可以理解 tools / skills，但授权仍然由 ControlKernel / ResourcePolicy 决定。
所有进入模型的 prompt section 后续都应通过 SoulProjection / PromptManifest 收束。
```
