# verifier_agent 配置计划书（2026-05-24）

## 1. 技术源报告

当前系统已经有三类相关结构：

- `agent:3` 健康管理 Agent：配置已被显式置为 `not_rebuilt`，不能假装它现在可执行。
- `worker.verification` 动态蓝图：可以临时 spawn 验证子 Agent，但它不是一个稳定的固定目标，主 Agent 不能天然识别为“交付复核专家”。
- `runtime.verification_review`：运行时可做硬验证和结构化收口判断，但这属于 runtime 验证层，不应该替主模型做语义审查，也不应该把语义判断塞成强制门禁。

缺口是：系统缺少一个固定、可见、可委派的语义复核子 Agent。它应该让主 Agent 在需要复核交付质量时主动调用，而不是由后端强制替模型验收或修补。

## 2. 推荐设计方向

新增固定内置专家 Agent：

```text
agent:verifier
```

它的职责是语义交付复核：

- 检查用户目标、最终回答、产物引用、证据包、工具观察是否互相支撑。
- 输出 `pass | needs_revision | blocked` 类型裁决。
- 指出缺失要求、无证据声明、需要返工的地方。
- 不修改文件，不替主 Agent 收口，不替 runtime 做硬门禁。

主 Agent 通过 `delegate_to_agent` 自主选择是否调用它。runtime 只负责：

- 校验委派权限；
- 启动子 Agent；
- 把 verifier 的结构化 verdict 回传给主 Agent；
- 记录事件和证据。

runtime 不自动调用 verifier，不根据 verifier 结果暗中改写最终答案。

## 3. 固定执行流

1. 主 Agent 在模型可见提示中看到 `agent:verifier` 的用途。
2. 主 Agent 判断当前任务需要交付复核时，调用 `delegate_to_agent`。
3. 委派请求使用 `delegation_kind`：
   - `completion_verification`
   - `semantic_verification`
   - `deliverable_review`
   - `artifact_review`
   - `quality_review`
   - `plan_review`
4. `AgentDelegationExecutor` 校验父 Agent 权限、目标 Agent 状态、目标 runtime profile。
5. `agent:verifier` 走 model-only 子 Agent 路径，不走 PDF/RAG/表格/Web 专用 MCP 路径。
6. verifier 返回结构化复核意见。
7. 主 Agent 根据复核意见继续修正、补证据或最终回答。

## 4. 文件级实施清单

- `backend/agent_system/registry/agent_registry.py`
  - 新增固定内置 `agent:verifier`。
- `backend/agent_system/profiles/runtime_profile_registry.py`
  - 给主 Agent 授权委派 verifier。
  - 新增 verifier runtime profile。
- `backend/agent_system/identity.py`
  - 新增 verifier 常用别名。
- `backend/orchestration/runtime_lane_registry.py`
  - 新增 `verification_delegate` lane。
  - 把专业模式可委派类型补上复核类 delegation kinds。
- `backend/orchestration/delegation_catalog.py`
  - 让委派目录显示 verifier 的 use when、输入契约和输出契约。
- `backend/orchestration/delegation_protocol.py`
  - 为复核类委派补充默认输出契约和角色说明。
- `backend/runtime/shared/context_manager.py`
  - 让主 Agent 在提示中看到 verifier 的职责和边界。
- `backend/runtime/execution/agent_delegation_executor.py`
  - 支持 model-only verifier 子 Agent 路径。
  - 把 verifier verdict 作为子 Agent 观察返回给主 Agent。
- 回归测试
  - 验证委派目录/提示可见。
  - 验证 `completion_verification` 可解析到 `agent:verifier`。
  - 验证 verifier 不被错误送入专用 MCP 路径。

## 5. 禁止事项

- 不复活 `agent:3` 健康管理旧链路。
- 不把 verifier 做成 runtime 强制门禁。
- 不让后端替主模型决定“必须调用 verifier”。
- 不用 verifier 结果自动伪造产物、修补最终答案或绕过硬验证。
