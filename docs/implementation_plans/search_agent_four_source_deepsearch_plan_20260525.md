# Search Agent 四源 DeepSearch 配置与测试计划

## 目标

把已注册的 Search Agent 配置为一个可装配的 DeepSearch 子 Agent，使它可以按 runtime_config 使用四类搜索源：

- Web search
- Local files search
- RAG / knowledge retrieval
- Memory search

所有能力必须经过编排系统的 AgentDescriptor、AgentRuntimeProfile、RuntimeConfig 和权限配置，不新增隐藏子 Agent，不新增独立 RAG runtime。

## 当前边界

- `agent:web_researcher` 已注册，当前是 Web 研究子 Agent。
- `SearchAgentRuntime` 已存在，但实际执行以 Web/Tavily 为主。
- 本地文件、RAG、Memory 能力分别存在于工具或 service 中，但还没有统一接入 DeepSearch 循环。

## 实施步骤

1. 配置层
   - 将 `agent:web_researcher` 定位为通用 Search Agent。
   - RuntimeProfile 的 `runtime_config.search.search_sources` 支持 `web`、`local_files`、`rag`、`memory`。
   - Profile 权限包含四类 source 所需 operation。

2. Runtime 层
   - 保留 `runtime.template.deepsearch`。
   - 扩展 `SearchAgentRuntime`，按 `search_sources` 调用 source provider。
   - 保留原有 Web DeepSearch 行为。
   - local/rag/memory provider 只返回统一候选证据，不直接替主 Agent 写最终答案。

3. 路由层
   - `ChildAgentRuntimeExecutor` 只要目标 Agent 配置了 `runtime.template.deepsearch`，就走 SearchAgentRuntime。
   - 不再只限制 Web 委派。
   - 未配置 DeepSearch 的 specialist 继续走原 MCP 专业能力路径。

4. 测试
   - 验证四类 source 的权限要求。
   - 验证 `agent:web_researcher` 默认 profile 已配置四源 DeepSearch。
   - 验证非 Web 委派可以路由到 SearchAgentRuntime。
   - 使用假 provider 测试 local/rag/memory 的候选证据进入 evidence packet。
   - 验证缺权限会失败，而不是静默降级。

## 不做

- 不新增 `RAGRuntime` 或 `LocalSearchRuntime`。
- 不新增未注册子 Agent。
- 不把 prompt 或权限写死在执行路径里。
- 不删除底层工具和 RetrievalService，它们是 source provider 的能力实现，不是残留代码。
