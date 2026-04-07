# MCP 扩展层

这是一个预留的 MCP（Model Context Protocol）扩展层骨架。

当前状态：

- 不连接任何 MCP server
- 不注册任何 MCP tools
- 不暴露任何 MCP resources
- 不影响现有 memory / RAG / tools 主链路

当前目的：

- 为后续接入 MCP 预留清晰目录边界
- 保持现有系统结构稳定
- 避免未来把 MCP 直接混进 memory 或 RAG 主逻辑

推荐定位：

- `durable_memory`：继续负责长期真值记忆
- `RAG`：继续负责本地知识检索
- `tools`：继续负责本地即时工具
- `mcp`：未来负责外部能力和外部资源的标准化接入

建议未来扩展方向：

1. MCP tools registry
2. MCP resources registry
3. MCP client bootstrap
4. Agent router 中的 MCP 路由策略

在真正接入 MCP 之前，这一层应保持“空扩展层”状态。
