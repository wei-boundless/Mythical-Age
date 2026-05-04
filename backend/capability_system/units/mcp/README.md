# MCP 能力单元层

这是能力系统下的 MCP（Model Context Protocol）能力单元层。

当前状态：

- 不连接任何 MCP server
- 不注册任何 MCP tools
- 不暴露任何 MCP resources
- 不影响现有 memory / retrieval / tools 主链路

当前目的：

- 为后续接入 MCP 预留清晰目录边界
- 把 MCP 作为能力单元纳入能力系统统一治理
- 避免未来把 MCP 直接混进其它业务子系统主逻辑

推荐定位：

- `durable_memory`：长期真值记忆
- `retrieval`：本地知识检索
- `tools`：本地即时工具执行层
- `capability_system/units/mcp`：外部能力与外部资源的标准化接入层

建议未来扩展方向：

1. MCP tools registry
2. MCP resources registry
3. MCP client bootstrap
4. 编排系统中的 MCP 路由策略

在真正接入 MCP 之前，这一层应保持“空扩展层”状态。
