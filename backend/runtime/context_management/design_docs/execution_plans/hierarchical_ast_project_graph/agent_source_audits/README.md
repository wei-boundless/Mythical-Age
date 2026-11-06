# 成熟 Agent 源码调研索引

状态：参考资料索引，服务于任务系统与运行底座重构  
日期：2026-07-04

## 1. 使用原则

本目录不是为了照搬外部项目，而是为了给本项目建立成熟标准：

```text
Turn != Session != TaskWorkEnvironment != AgentExecutionEpisode != WorkProduct
```

外部系统的价值在于校准工程边界：

- turn 是一次模型交互或用户交互边界；
- session 是对话和用户入口连续性；
- task 是可恢复、可审计、可持久推进的工作环境；
- run / episode 是 agent 进入环境执行的一段过程；
- work product 是系统和下游可以消费的产物，不等于 assistant final answer。

## 2. 推荐阅读顺序

| 顺序 | 文档 | 主要用途 |
| --- | --- | --- |
| 1 | `00_turn_session_task_reference_synthesis.md` | 汇总所有外部系统调研结论，沉淀本项目任务框架不变量 |
| 2 | `01_openai_codex_turn_task_mechanism_audit.md` | 参考 Codex 的 turn/session/runtime 边界、工具执行与上下文控制 |
| 3 | `02_claude_code_nb_turn_task_mechanism_audit.md` | 参考 Claude Code 类系统的 coding agent 上下文与任务推进方式 |
| 4 | `03_opencode_dev_turn_task_mechanism_audit.md` | 参考 OpenCode 开发分支的 agent 运行机制 |
| 5 | `04_opencode_main_turn_task_mechanism_audit.md` | 参考 OpenCode 主线的会话、工具和运行组织 |
| 6 | `05_openclaw_turn_task_flow_runtime_mechanism_audit.md` | 参考 OpenClaw 的 task flow / runtime 分层 |
| 7 | `06_dify_workflow_conversation_run_mechanism_audit.md` | 参考 Dify workflow / conversation / run 的边界 |
| 8 | `07_dify_agent_agenton_run_snapshot_mechanism_audit.md` | 参考 Dify agent run snapshot 和恢复机制 |
| 9 | `08_hermes_agent_gateway_kanban_task_environment_mechanism_audit.md` | 参考 Hermes gateway / kanban / task environment 的任务管理视角 |
| 10 | `09_pi_agent_harness_session_runtime_mechanism_audit.md` | 参考 Pi agent harness / session / runtime 的交互方式 |

## 3. 对本项目的直接约束

这些调研共同支持以下裁决：

- 不把复杂 turn 误当成 task。
- 不把 task 压扁成 todo。
- 不让 session transcript 成为任务真相。
- 不让 graph node 直接成为 agent execution。
- 不让 assistant final answer 成为唯一产物。
- 不把恢复做成重放旧上下文。
- 不在 graph runtime 里新增第二套模型 loop。
- 不让系统替 agent 做语义判断。

## 4. 对应主设计文档

调研结论已经汇总进这些主文档：

- [../16_unified_agent_task_project_control_overall_plan.md](../16_unified_agent_task_project_control_overall_plan.md)
- [../17_task_graph_runtime_interface_detail_alignment.md](../17_task_graph_runtime_interface_detail_alignment.md)
- [../18_task_environment_runtime_mechanics_plan.md](../18_task_environment_runtime_mechanics_plan.md)
- [../19_task_framework_canonical_definition_and_agent_system_contract.md](../19_task_framework_canonical_definition_and_agent_system_contract.md)

后续实施时优先执行主设计文档；本目录用于追溯成熟 agent 标准和校验设计没有退化。
