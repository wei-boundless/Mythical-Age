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
- `01-AgentRuntime当前框架对照与缺口分析-20260430.md`
- `02-Claude-Code源码细节借鉴与AgentRuntime补强建议-20260430.md`
- `03-AgentRuntime先进框架范式汇总-20260430.md`
- `04-AgentRuntime任务导向持久化工作流设计-20260430.md`
- `05-AgentRuntime当前结构梳理与架构决策基线-20260430.md`
- `06-Codex持久化循环架构对照与TaskRunLoop移植报告-20260430.md`
- `07-AgentRuntime统一Loop架构重审与整改方案-20260430.md`
- `08-Runtime与Loop本质分析-Claude-Code与Codex循环策略-20260430.md`
- `09-Claude-Code式单Agent统一Loop系统补全计划-20260430.md`
- `10-单Agent统一Loop施工留痕-20260430.md`
- `11-测试系统后端重构施工留痕-20260430.md`
- `12-测试Agent与测试文件治理方案-20260430.md`
- `13-AgentRuntime前端系统页面设计与管理说明-20260430.md`
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
洪荒时代不是一个更大的 query runtime，而是一套由 OrchestrationSystem.TaskRunLoop 统一驱动的 agent runtime。
先进架构的核心是统一 loop；编排系统拥有唯一调度权。
loop 的本质就是受状态、预算、权限、上下文、工具结果和错误恢复控制的 `while true`。
当前施工蓝图以 `09-Claude-Code式单Agent统一Loop系统补全计划-20260430.md` 为准：先完成 Claude Code 式单 agent 统一 TaskRunLoop，再讨论多 agent 拓扑和交互协议。
任务、记忆、灵魂、操作、输出、写回系统不是平行推进者，而是统一 loop 调用的专业阶段服务。
灵魂系统不是语气包，而是智能体意志管理层。
灵魂可以理解 tools / skills，但授权仍然由 OperationGate / ResourcePolicy 决定。
所有进入模型的 prompt section 后续都应通过 SoulProjection / PromptManifest 收束。
旧 query 层应逐步退化为请求入口、事件流和过渡 adapter。
```

当前施工状态：

```text
灵魂系统：已完成主要重构。
任务系统：preview contract 已接入。
操作系统：ResourcePolicyPreview 已接入。
编排系统：single_agent preview 控制面已收口，RuntimeDirective / OperationGate 前置合同已落地；TaskRunLoop 的事件/检查点留痕底座已落地，并已开始包住 model-only 主链，但正式 Adoption / ContextManager / CommitGate close 仍未完成。
记忆系统：三层记忆、MemoryRuntimeView、ContextPolicyPreview、MemoryGate blocked 与治理记录已落地，真实写回仍等待 CommitGate。
query 旧层：生产源码层面已完成激进清理；`backend/query` 只剩入口 adapter 三件套，旧 planner / direct tool / follow-up / runtime context 已删除，output / prompt / evidence / worker 能力已迁出到独立系统包，model-only 执行 lane 已迁入 `backend/execution`，runtime chain 装配已迁入 `backend/runtime/agent_chain.py`。
当前主要缺口：RuntimeContextManager、正式 Adoption 管线、CommitGate / OutputCommitPlan / CommitApplier、只读 ToolExecutor / WorkerExecutor、多 AgentSeat 运行态拓扑、新测试体系。
```
