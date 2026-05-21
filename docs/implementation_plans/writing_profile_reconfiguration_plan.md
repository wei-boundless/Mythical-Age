# 写作编排 Profile 重配置计划

## 目标

为模块化长篇写作任务图配置专用运行 profile，使创作、审核、记忆提交节点都以“已装配上下文内的文本产物”为工作材料，不把文件读取、搜索或工具标签当成可执行动作，避免返修流程中出现伪工具调用、产物占位和记忆污染。

## 实施范围

1. 写作任务图配置脚本：重配 worker、memory steward、runtime monitor 的运行 profile 元数据、上下文可见范围和禁止操作说明。
2. 节点执行消息：返修交接包必须把审核报告、上一版候选产物和相关上下文正文展开给模型，不能只暴露 artifact 引用。
3. 产物验收：正式文本产物中出现 `<read_file>`、工具调用标记、DSML 等协议文本时，判为不可接受，走断点返修。
4. 回归测试：覆盖 profile 配置、返修正文展开和伪工具产物拒收。
5. 重配并验证：重新生成写作任务图配置，保证后续断点续跑使用新 profile 与新边界。

## 成功标准

- 写作 worker profile 不允许读写文件、搜索、shell、委派等工具操作，只允许模型产出、授权记忆读取和文本度量。
- profile metadata 明确标注 `text_artifact_runtime`、`preexpanded_context_required`、`pseudo_tool_output_forbidden`。
- 返修节点提示词中直接包含上一版候选产物和审核报告正文片段。
- 任何 `<read_file>` 式最终产物不会被当作正式 artifact 接受。
- 相关回归测试通过。
