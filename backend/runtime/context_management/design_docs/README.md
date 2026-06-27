# Context Management Design Docs

本目录保存 agent runtime、语义空间、能力系统、缓存/provider 传输和执行链路的设计资料。

## 入口文档

- `semantic_space/agent_semantic_operating_model_20260628.md`：上层 Agent Semantic Operating Model。
- `execution_plans/harness_neural_system_consolidation_plan_20260628.md`：harness 神经控制体系收束、分集和 graph system 独立的总实施方案。
- `execution_plans/total_neural_architecture_audit_20260628.md`：后端总神经架构审计，按语义模型审查 harness、graph、runtime、orchestration 和旧神经结构清理边界。
- `execution_plans/system_ownership_directory_audit_20260628.md`：项目总目录和后端一级系统归属审计，明确每个系统的权威、模糊目录裁决和命名治理规则。
- `execution_plans/backend_code_structure_semantic_refactor_plan_20260628.md`：按语义空间模型整理后端代码结构的迁移计划。
- `execution_plans/graph_system_independence_plan_20260628.md`：把图结构、图状态机和图运行从 harness 独立为 graph system 的迁移计划。
- `semantic_space/agent_semantic_space_context_design_20260627.md`：已有语义空间上下文规范。
- `execution_plans/context_pipeline_standardization_refactor_plan.md`：上下文流水线和物理拼接计划。
- `capability_tools/capability_system_standardization_plan_20260627.md`：Tools / MCP / Skills 能力系统计划。

## 目录分层

- `semantic_space/`：agent 语义空间、语义图、上下文分层和产品模型。
- `capability_tools/`：工具契约、provider tools、MCP、Skills、能力供给。
- `execution_plans/`：runtime、task mode、interruptible control、代码结构迁移计划。
- `cache_provider/`：prompt cache、DeepSeek/provider adapter、prefix envelope、provider-visible context 策略。

## 维护规则

- 总体后端神经架构边界以 `execution_plans/total_neural_architecture_audit_20260628.md` 为准。
- 代码结构迁移细节以 `execution_plans/backend_code_structure_semantic_refactor_plan_20260628.md` 为参考，但不能覆盖总审计中的权威边界。
- 新增架构文档必须归入上述四类之一，不再堆到 `context_management` 根目录。
- `design_docs` 是可追踪目录；不要使用名为 `docs` 的子目录，因为项目 `.gitignore` 会忽略它。
